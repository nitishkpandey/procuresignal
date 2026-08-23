"""Subject requests: what we hold about a person.

Anyone may ask for their own data without a role, because the right of access belongs to
the person and not to their employer's administrator. An admin may ask on behalf of
someone in their own organization, because a subject request usually arrives by email to
the company rather than through the product.

Every request is itself audited. A record of what was disclosed, to whom, and when is the
part a regulator asks for after the fact.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from procuresignal.auth.audit import record_audit
from procuresignal.models import Membership, Role, User
from procuresignal.privacy.subject import erase_subject, export_subject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    AuthenticatedUser,
    ClientContext,
    get_client_context,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas.privacy import (
    ErasureReceiptResponse,
    ErasureRequest,
    SubjectExportResponse,
)

router = APIRouter(
    prefix="/api/privacy", tags=["privacy"], dependencies=[Depends(get_current_user)]
)

_ADMIN = Depends(require_role(Role.ADMIN))


async def _colleague(session: AsyncSession, public_id: str, caller: AuthenticatedUser) -> User:
    """A user in the caller's own organization.

    404 rather than 403 for somebody else's: confirming that an account exists is how
    a directory gets enumerated, and here the id is an email-shaped fact about a person.
    """

    user = (
        await session.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(User.public_id == public_id)
            .where(Membership.organization_id == caller.organization_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _audited_export(
    session: AsyncSession,
    *,
    subject: User,
    actor: AuthenticatedUser,
    context: ClientContext,
    on_behalf: bool,
) -> SubjectExportResponse:
    export = await export_subject(session, user=subject)

    await record_audit(
        session,
        action="privacy.subject_export",
        outcome="success",
        actor=actor,
        resource_type="user",
        resource_id=subject.public_id,
        detail={
            "on_behalf_of_another": on_behalf,
            # Row counts rather than the rows: the audit log must record that a
            # disclosure happened without becoming a second copy of the disclosure.
            "row_counts": {name: len(rows) for name, rows in export.tables.items()},
        },
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return SubjectExportResponse(
        subject=export.subject, generated_at=export.generated_at, tables=export.tables
    )


@router.get("/me/export", response_model=SubjectExportResponse)
async def export_own_data(
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> SubjectExportResponse:
    """Everything held about the caller. No role required — this is their own data."""

    subject = await session.get(User, current_user.id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await _audited_export(
        session, subject=subject, actor=current_user, context=context, on_behalf=False
    )


@router.get(
    "/users/{public_id}/export", response_model=SubjectExportResponse, dependencies=[_ADMIN]
)
async def export_user_data(
    public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> SubjectExportResponse:
    """Everything held about someone in the caller's organization."""

    subject = await _colleague(session, public_id, current_user)

    return await _audited_export(
        session, subject=subject, actor=current_user, context=context, on_behalf=True
    )


@router.post(
    "/users/{public_id}/erase", response_model=ErasureReceiptResponse, dependencies=[_ADMIN]
)
async def erase_user_data(
    public_id: str,
    payload: ErasureRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> ErasureReceiptResponse:
    """Erase someone in the caller's organization, and return a receipt.

    Irreversible, and admin-only rather than self-service: the requester is usually not
    the subject, and there is no verified-identity flow to hang self-service off yet.
    """

    subject = await _colleague(session, public_id, current_user)

    if subject.id == current_user.id:
        # Erasing yourself through this endpoint destroys the session making the
        # request and can leave an organization with no administrator. A second admin
        # handles it, which is also the segregation an auditor expects.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Another administrator must erase your account.",
        )

    # Written before the subject disappears, and committed by erase_subject's own
    # commit. The trail has to name what was about to happen even if the delete fails.
    await record_audit(
        session,
        action="privacy.subject_erased",
        outcome="success",
        actor=current_user,
        resource_type="user",
        resource_id=subject.public_id,
        detail={"reason": payload.reason},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )

    receipt = await erase_subject(session, user=subject, reason=payload.reason)

    return ErasureReceiptResponse(
        subject_public_id=receipt.subject_public_id,
        erased_at=receipt.erased_at,
        reason=receipt.reason,
        deleted=receipt.deleted,
        anonymised=receipt.anonymised,
        retained=receipt.retained,
    )
