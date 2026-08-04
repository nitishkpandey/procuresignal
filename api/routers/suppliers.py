"""Supplier registry endpoints.

Reads are open to any member; every change needs an admin, because supplier identity
decides what sanctions screening matches.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.auth.audit import record_audit
from procuresignal.models import ArticleSupplierMention, Role, Supplier, SupplierAlias
from procuresignal.suppliers.normalization import normalize
from procuresignal.suppliers.registry import (
    AmbiguousAliasError,
    DuplicateSupplierError,
    SupplierRegistryError,
    add_alias,
    merge_suppliers,
    register_supplier,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    AuthenticatedUser,
    ClientContext,
    get_client_context,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas.supplier import (
    AliasCreate,
    AliasResponse,
    MergeRequest,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    UnresolvedListResponse,
    UnresolvedName,
)

router = APIRouter(
    prefix="/api/suppliers", tags=["suppliers"], dependencies=[Depends(get_current_user)]
)

_ADMIN = Depends(require_role(Role.ADMIN))


async def _load(session: AsyncSession, public_id: str) -> Supplier:
    supplier = (
        await session.execute(select(Supplier).where(Supplier.public_id == public_id))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


# Declared before the "{public_id}" routes so the literal segment wins the match.
@router.get("/unresolved", response_model=UnresolvedListResponse)
async def list_unresolved(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> UnresolvedListResponse:
    """Supplier names the registry could not place, most frequent first.

    This is the work queue. It is why mentions, screening, and the backfill all keep
    the names they could not resolve rather than discarding them: without it, registry
    coverage is a number nobody can act on.
    """

    rows = (
        await session.execute(
            select(
                ArticleSupplierMention.surface_form,
                func.count(ArticleSupplierMention.id).label("mention_count"),
            )
            .where(ArticleSupplierMention.supplier_id.is_(None))
            .group_by(ArticleSupplierMention.surface_form)
            .order_by(func.count(ArticleSupplierMention.id).desc())
            .limit(limit)
        )
    ).all()

    items = [
        UnresolvedName(surface_form=surface_form, mention_count=count)
        for surface_form, count in rows
    ]
    return UnresolvedListResponse(items=items, total_count=len(items))


@router.get("", response_model=SupplierListResponse)
async def list_suppliers(
    q: str | None = Query(None, max_length=300),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SupplierListResponse:
    """List active suppliers, optionally matching a name or any of its aliases."""

    statement = select(Supplier).where(Supplier.is_active.is_(True))

    if q and normalize(q):
        # Searching aliases too, so looking up "Bosch" finds "Robert Bosch GmbH".
        statement = statement.where(
            Supplier.id.in_(
                select(SupplierAlias.supplier_id).where(
                    SupplierAlias.normalized_alias.contains(normalize(q))
                )
            )
        )

    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = (
        (
            await session.execute(
                statement.order_by(Supplier.canonical_name).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return SupplierListResponse(
        items=[SupplierResponse.model_validate(row) for row in rows],
        total_count=int(total or 0),
    )


@router.post(
    "", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED, dependencies=[_ADMIN]
)
async def create_supplier(
    payload: SupplierCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> SupplierResponse:
    """Register a supplier and the aliases derived from its name."""

    try:
        supplier = await register_supplier(
            session,
            canonical_name=payload.canonical_name,
            country=payload.country,
            lei=payload.lei,
        )
    except (DuplicateSupplierError, AmbiguousAliasError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except SupplierRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    await record_audit(
        session,
        action="supplier.create",
        outcome="success",
        actor=current_user,
        resource_type="supplier",
        resource_id=supplier.public_id,
        detail={"canonical_name": supplier.canonical_name, "country": supplier.country},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
    return SupplierResponse.model_validate(supplier)


@router.post(
    "/{public_id}/aliases",
    response_model=AliasResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_ADMIN],
)
async def create_alias(
    public_id: str,
    payload: AliasCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> AliasResponse:
    """Teach the registry another name for a supplier."""

    supplier = await _load(session, public_id)

    try:
        alias = await add_alias(session, supplier_id=supplier.id, alias=payload.alias)
    except AmbiguousAliasError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    await record_audit(
        session,
        action="supplier.alias_add",
        outcome="success",
        actor=current_user,
        resource_type="supplier",
        resource_id=public_id,
        detail={"alias": payload.alias},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    if alias is None:
        # Already held by this supplier; repeating yourself is not an error.
        return AliasResponse(
            alias=payload.alias, normalized_alias=normalize(payload.alias), source="manual"
        )
    return AliasResponse.model_validate(alias)


@router.post("/{public_id}/merge", response_model=SupplierResponse, dependencies=[_ADMIN])
async def merge(
    public_id: str,
    payload: MergeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> SupplierResponse:
    """Fold one supplier into another, keeping the loser deactivated for audit."""

    keep = await _load(session, public_id)
    duplicate = await _load(session, payload.merge_public_id)

    try:
        await merge_suppliers(session, keep_id=keep.id, merge_id=duplicate.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    await record_audit(
        session,
        action="supplier.merge",
        outcome="success",
        actor=current_user,
        resource_type="supplier",
        resource_id=keep.public_id,
        detail={"merged_public_id": duplicate.public_id, "merged_name": duplicate.canonical_name},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
    return SupplierResponse.model_validate(keep)
