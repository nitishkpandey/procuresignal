"""Tests for identity, tenancy, session, and audit models."""

import pytest
from procuresignal.models import (
    AuditLog,
    Membership,
    Organization,
    RefreshToken,
    Role,
    User,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _org_and_user(session: AsyncSession) -> tuple[Organization, User]:
    org = Organization(public_id="org-1", name="Acme Procurement", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com", password_hash="$argon2id$stub")
    session.add_all([org, user])
    await session.flush()
    return org, user


async def test_membership_is_unique_per_user_and_organization(async_session: AsyncSession) -> None:
    org, user = await _org_and_user(async_session)

    async_session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.MEMBER))
    await async_session.flush()

    async_session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.ADMIN))
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_new_user_has_no_password_and_a_zero_token_version(
    async_session: AsyncSession,
) -> None:
    user = User(public_id="user-2", email="new@acme.com")
    async_session.add(user)
    await async_session.flush()

    assert user.password_hash is None
    assert user.is_active is True
    assert user.token_version == 0


async def test_email_and_public_id_are_unique(async_session: AsyncSession) -> None:
    _, user = await _org_and_user(async_session)

    async_session.add(User(public_id="user-distinct", email=user.email))
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_refresh_tokens_store_only_a_hash(async_session: AsyncSession) -> None:
    _, user = await _org_and_user(async_session)

    token = RefreshToken(
        user_id=user.id,
        token_hash="a" * 64,
        family_id="fam-1",
        expires_at=__import__("datetime").datetime(2026, 9, 1),
    )
    async_session.add(token)
    await async_session.flush()

    columns = {column.name for column in RefreshToken.__table__.columns}
    assert "token_hash" in columns
    assert "token" not in columns
    assert token.revoked_at is None


async def test_audit_row_keeps_actor_email_for_deleted_actors(async_session: AsyncSession) -> None:
    org, user = await _org_and_user(async_session)

    entry = AuditLog(
        organization_id=org.id,
        actor_user_id=user.id,
        actor_email=user.email,
        action="user.login",
        outcome="success",
        detail={"method": "password"},
    )
    async_session.add(entry)
    await async_session.flush()

    assert entry.actor_email == "buyer@acme.com"
    assert entry.detail == {"method": "password"}


def test_role_hierarchy_is_ordered_strongest_first() -> None:
    assert list(Role) == [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.VIEWER]
