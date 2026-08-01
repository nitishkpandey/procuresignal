"""API dependency helpers."""

from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Optional

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from procuresignal.auth import decode_access_token
from procuresignal.config import database
from procuresignal.models import Membership, Organization, Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_bearer_scheme = HTTPBearer(auto_error=False)

# Offered by the client alongside the token itself, and echoed back on accept so the
# browser does not fail the handshake.
WEBSOCKET_BEARER_SUBPROTOCOL = "bearer"
# Private-use close code mirroring HTTP 401; 1008 (policy violation) would not
# distinguish authentication from any other refusal.
WS_UNAUTHENTICATED = 4401

# Roles are declared strongest first, so a lower index outranks a higher one.
_ROLE_RANK = {role: index for index, role in enumerate(Role)}


@dataclass(frozen=True)
class AuthenticatedUser:
    """The identity behind a request, resolved server-side from the access token."""

    id: int
    public_id: str
    email: str
    organization_id: int
    organization_public_id: str
    role: Role


@dataclass(frozen=True)
class ClientContext:
    """Request metadata recorded alongside audited actions."""

    client_ip: str | None
    user_agent: str | None


def _unauthenticated() -> HTTPException:
    """One rejection for every failure mode.

    Distinguishing "no such user" from "wrong organization" from "disabled account"
    would let a caller enumerate accounts by reading the error.
    """

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for API handlers."""

    db_config = database.db_config
    if db_config is None or db_config.session_maker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    async with db_config.session_maker() as session:
        yield session


def get_client_context(request: Request) -> ClientContext:
    """Extract audit metadata from the request.

    # ponytail: reads the direct peer only. X-Forwarded-For is spoofable without a
    # trusted proxy in front, and there is no deployment topology to trust yet.
    """

    return ClientContext(
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def resolve_access_token(token: str, session: AsyncSession) -> Optional[AuthenticatedUser]:
    """Turn a raw access token into an identity, or `None` if it is not usable.

    The user and membership are re-read every time, and the token's version claim is
    compared against the stored one. That costs an indexed query per call and buys
    immediate revocation instead of waiting out the token's remaining lifetime.

    Shared by the HTTP and WebSocket entry points so the two cannot drift apart.
    """

    if not token:
        return None

    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError:
        return None

    row = (
        await session.execute(
            select(User, Membership, Organization)
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(User.public_id == claims.subject)
            .where(Organization.public_id == claims.organization)
        )
    ).first()
    if row is None:
        return None

    user, membership, organization = row
    if not user.is_active or user.token_version != claims.token_version:
        return None

    return AuthenticatedUser(
        id=user.id,
        public_id=user.public_id,
        email=user.email,
        organization_id=organization.id,
        organization_public_id=organization.public_id,
        role=Role(membership.role),
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """Resolve the caller of an HTTP request from their bearer token."""

    if credentials is None:
        raise _unauthenticated()

    resolved = await resolve_access_token(credentials.credentials, session)
    if resolved is None:
        raise _unauthenticated()
    return resolved


def access_token_from_subprotocols(websocket: WebSocket) -> Optional[str]:
    """Read the access token from `Sec-WebSocket-Protocol`.

    Browsers cannot set an Authorization header on a WebSocket, and a query string
    would put the token into access logs, proxy logs, and browser history. The
    subprotocol header is the remaining place a browser can put a credential.

    The client offers two values: the literal "bearer" and the token itself.
    """

    protocols = websocket.scope.get("subprotocols") or []
    if len(protocols) == 2 and protocols[0] == WEBSOCKET_BEARER_SUBPROTOCOL:
        return protocols[1]
    return None


async def get_current_ws_user(
    websocket: WebSocket,
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """Resolve the caller of a WebSocket, closing the socket before accepting it."""

    token = access_token_from_subprotocols(websocket)
    resolved = await resolve_access_token(token or "", session)
    if resolved is None:
        raise WebSocketException(code=WS_UNAUTHENTICATED, reason="Not authenticated")
    return resolved


def require_role(
    minimum: Role,
) -> Callable[..., Coroutine[Any, Any, AuthenticatedUser]]:
    """Admit callers holding `minimum` or any stronger role."""

    async def dependency(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if _ROLE_RANK[current_user.role] > _ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency
