"""Tests for request identity resolution and role enforcement."""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from procuresignal.auth import AccessClaims, encode_access_token
from procuresignal.models import Base, Membership, Organization, Role, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.dependencies import AuthenticatedUser, get_current_user, require_role

SECRET = "test-secret-key-that-is-long-enough-32"


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as active:
        yield active


@pytest.fixture
async def member(session: AsyncSession) -> User:
    org = Organization(public_id="org-1", name="Acme", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com", password_hash="$argon2id$stub")
    session.add_all([org, user])
    await session.flush()
    session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.MEMBER))
    await session.flush()
    return user


def credentials_for(
    user: User,
    *,
    organization: str = "org-1",
    role: str = Role.MEMBER,
    token_version: int | None = None,
) -> HTTPAuthorizationCredentials:
    token = encode_access_token(
        AccessClaims(
            subject=user.public_id,
            organization=organization,
            role=role,
            token_version=user.token_version if token_version is None else token_version,
            jti="jti-1",
        )
    )
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_valid_token_resolves_the_user_and_organization(
    session: AsyncSession, member: User
) -> None:
    resolved = await get_current_user(credentials=credentials_for(member), session=session)

    assert resolved == AuthenticatedUser(
        id=member.id,
        public_id="user-1",
        email="buyer@acme.com",
        organization_id=1,
        organization_public_id="org-1",
        role=Role.MEMBER,
    )


async def test_bumping_token_version_revokes_outstanding_tokens(
    session: AsyncSession, member: User
) -> None:
    """Revocation must take effect on the next request, not at token expiry."""
    issued = credentials_for(member)
    member.token_version += 1
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=issued, session=session)
    assert exc.value.status_code == 401


async def test_deactivated_user_is_refused(session: AsyncSession, member: User) -> None:
    issued = credentials_for(member)
    member.is_active = False
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=issued, session=session)
    assert exc.value.status_code == 401


async def test_token_for_an_organization_the_user_does_not_belong_to_is_refused(
    session: AsyncSession, member: User
) -> None:
    forged = credentials_for(member, organization="org-someone-else")

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=forged, session=session)
    assert exc.value.status_code == 401


async def test_unknown_subject_is_refused(session: AsyncSession, member: User) -> None:
    ghost = User(public_id="user-does-not-exist", email="ghost@acme.com")
    forged = credentials_for(ghost)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=forged, session=session)
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "bad",
    [None, HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-token")],
)
async def test_missing_or_malformed_credentials_are_refused(session: AsyncSession, bad) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=bad, session=session)
    assert exc.value.status_code == 401


async def test_every_rejection_looks_identical(session: AsyncSession, member: User) -> None:
    """A distinguishable failure reveals whether an account exists or was disabled."""
    ghost = User(public_id="nobody", email="nobody@acme.com")
    rejections = []

    for credentials in (None, credentials_for(ghost), credentials_for(member, organization="x")):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(credentials=credentials, session=session)
        rejections.append(
            (
                exc.value.status_code,
                exc.value.detail,
                tuple(sorted((exc.value.headers or {}).items())),
            )
        )

    assert len(set(rejections)) == 1, rejections


def _user(role: Role) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=1,
        public_id="u",
        email="u@acme.com",
        organization_id=1,
        organization_public_id="o",
        role=role,
    )


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MEMBER])
async def test_roles_at_or_above_the_minimum_are_admitted(role: Role) -> None:
    """Superior roles must inherit, or every call site has to list them all."""
    assert await require_role(Role.MEMBER)(current_user=_user(role)) == _user(role)


async def test_role_below_the_minimum_is_refused() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_role(Role.MEMBER)(current_user=_user(Role.VIEWER))
    assert exc.value.status_code == 403


async def test_owner_only_route_refuses_an_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_role(Role.OWNER)(current_user=_user(Role.ADMIN))
    assert exc.value.status_code == 403
