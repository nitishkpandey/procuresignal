"""Authentication endpoints."""

from os import getenv
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from procuresignal.auth import service
from procuresignal.auth.audit import record_audit
from procuresignal.auth.tokens import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL
from procuresignal.models import Organization, Role, User
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
from api.rate_limit import (
    check_login,
    check_registration,
    login_key,
    record_login_failure,
    record_registration_failure,
    registration_key,
)
from api.schemas.auth import (
    AccessTokenResponse,
    InvitationRequest,
    InvitationResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "procuresignal_refresh"
# Scoped so the browser only sends the refresh token to the endpoints that rotate it,
# rather than attaching it to every ordinary API call.
REFRESH_COOKIE_PATH = "/api/auth"


def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _cookies_require_https() -> bool:
    """Secure cookies everywhere except explicit local development over plain HTTP."""

    return getenv("AUTH_COOKIE_INSECURE", "false").strip().lower() not in {"true", "1", "yes"}


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        httponly=True,
        secure=_cookies_require_https(),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _user_response(issued: service.IssuedSession) -> UserResponse:
    return UserResponse(
        user_id=issued.user.public_id,
        email=issued.user.email,
        full_name=issued.user.full_name,
        organization_id=issued.organization.public_id,
        organization_name=issued.organization.name,
        role=str(issued.role),
    )


def _token_response(issued: service.IssuedSession, response: Response) -> TokenResponse:
    _set_refresh_cookie(response, issued.refresh_token)
    return TokenResponse(
        access_token=issued.access_token,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
        user=_user_response(issued),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
) -> TokenResponse:
    """Create an account, its organization if needed, and an initial session."""

    throttle_key = registration_key(context.client_ip)
    retry_after = await check_registration(throttle_key)
    if retry_after is not None:
        raise _too_many_attempts(retry_after)

    try:
        issued = await service.register(
            session,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            invitation_token=payload.invitation_token,
            user_agent=context.user_agent,
            client_ip=context.client_ip,
        )
    except service.InvitationAlreadyUsedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except service.InvalidInvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except service.EmailAlreadyRegisteredError:
        await record_registration_failure(throttle_key)
        await record_audit(
            session,
            action="user.register",
            outcome="failure",
            detail={"email": service.normalize_email(payload.email), "reason": "already_exists"},
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None

    await record_audit(
        session,
        action="user.register",
        outcome="success",
        organization_id=issued.organization.id,
        resource_type="user",
        resource_id=issued.user.public_id,
        detail={"email": issued.user.email, "role": str(issued.role)},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
    # Successes count too. Limiting only failures meant an attacker using a fresh
    # address each time never approached the cap, which is the shape of the abuse
    # worth stopping: unlimited account and organization creation.
    await record_registration_failure(throttle_key)
    return _token_response(issued, response)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
) -> TokenResponse:
    """Exchange credentials for a session."""

    throttle_key = login_key(context.client_ip, payload.email)
    retry_after = await check_login(throttle_key)
    if retry_after is not None:
        raise _too_many_attempts(retry_after)

    try:
        issued = await service.authenticate(
            session,
            email=payload.email,
            password=payload.password,
            user_agent=context.user_agent,
            client_ip=context.client_ip,
        )
    except service.InvalidCredentialsError:
        await record_login_failure(throttle_key)
        await record_audit(
            session,
            action="user.login",
            outcome="failure",
            detail={"email": service.normalize_email(payload.email)},
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
        await session.commit()
        raise _INVALID_CREDENTIALS from None

    await record_audit(
        session,
        action="user.login",
        outcome="success",
        organization_id=issued.organization.id,
        resource_type="user",
        resource_id=issued.user.public_id,
        detail={"email": issued.user.email},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
    return _token_response(issued, response)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
    presented: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
) -> AccessTokenResponse:
    """Rotate the refresh token and mint a new access token."""

    if not presented:
        raise _INVALID_CREDENTIALS

    try:
        issued = await service.rotate_refresh_token(
            session,
            presented=presented,
            user_agent=context.user_agent,
            client_ip=context.client_ip,
        )
    except service.InvalidCredentialsError:
        await record_audit(
            session,
            action="session.refresh",
            outcome="failure",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
        await session.commit()
        _clear_refresh_cookie(response)
        raise _INVALID_CREDENTIALS from None

    await session.commit()
    _set_refresh_cookie(response, issued.refresh_token)
    return AccessTokenResponse(
        access_token=issued.access_token,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
    presented: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
) -> Response:
    """End the current session. Safe to call without a valid session."""

    if presented:
        await service.revoke_token(session, presented)
        await record_audit(
            session,
            action="session.logout",
            outcome="success",
            client_ip=context.client_ip,
            user_agent=context.user_agent,
        )
        await session.commit()

    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/revoke-all-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
) -> Response:
    """Sign out everywhere, including access tokens that have not yet expired."""

    await service.revoke_all_sessions(session, current_user.id)
    await record_audit(
        session,
        action="session.revoke_all",
        outcome="success",
        actor=current_user,
        resource_type="user",
        resource_id=current_user.public_id,
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Return the authenticated identity."""

    user, organization = (
        await session.execute(
            select(User, Organization)
            .join(Organization, Organization.id == current_user.organization_id)
            .where(User.id == current_user.id)
        )
    ).one()

    return UserResponse(
        user_id=current_user.public_id,
        email=current_user.email,
        full_name=user.full_name,
        organization_id=organization.public_id,
        organization_name=organization.name,
        role=str(Role(current_user.role)),
    )


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def invite(
    payload: InvitationRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    context: ClientContext = Depends(get_client_context),
) -> InvitationResponse:
    """Offer one address a place in the caller's organization.

    This is the only way into an existing tenant. Registration alone creates a new one,
    because a matching email domain proves nothing about who is typing.
    """

    invitation, token = await service.create_invitation(
        session,
        organization_id=current_user.organization_id,
        email=payload.email,
        role=Role(payload.role),
        invited_by_user_id=current_user.id,
    )
    await record_audit(
        session,
        action="organization.invite",
        outcome="success",
        actor=current_user,
        resource_type="organization",
        resource_id=current_user.organization_public_id,
        detail={"email": invitation.email, "role": invitation.role},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return InvitationResponse(
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        token=token,
    )
