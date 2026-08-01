"""Tests for the append-only audit writer."""

import pytest
from procuresignal.auth.audit import record_audit, scrub
from procuresignal.models import AuditLog, Base, Membership, Organization, Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.dependencies import AuthenticatedUser


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as active:
        yield active


@pytest.fixture
async def actor(session: AsyncSession) -> AuthenticatedUser:
    org = Organization(public_id="org-1", name="Acme", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com")
    session.add_all([org, user])
    await session.flush()
    session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.MEMBER))
    await session.flush()
    return AuthenticatedUser(
        id=user.id,
        public_id=user.public_id,
        email=user.email,
        organization_id=org.id,
        organization_public_id=org.public_id,
        role=Role.MEMBER,
    )


async def _rows(session: AsyncSession) -> list[AuditLog]:
    return list((await session.execute(select(AuditLog))).scalars().all())


async def test_records_the_actor_and_action(session: AsyncSession, actor) -> None:
    await record_audit(session, action="user.login", actor=actor, outcome="success")
    await session.flush()

    row = (await _rows(session))[0]
    assert row.action == "user.login"
    assert row.outcome == "success"
    assert row.actor_user_id == actor.id
    assert row.actor_email == "buyer@acme.com"
    assert row.organization_id == actor.organization_id


async def test_records_failures_without_an_actor(session: AsyncSession) -> None:
    """A failed login has no authenticated actor but still needs a trail."""
    await record_audit(
        session,
        action="user.login",
        actor=None,
        outcome="failure",
        detail={"email": "unknown@acme.com"},
    )
    await session.flush()

    row = (await _rows(session))[0]
    assert row.actor_user_id is None
    assert row.outcome == "failure"
    assert row.detail == {"email": "unknown@acme.com"}


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "PASSWORD", "token", "refresh_token", "secret", "authorization"],
)
async def test_credentials_are_never_persisted(session: AsyncSession, actor, key: str) -> None:
    await record_audit(
        session, action="user.login", actor=actor, outcome="success", detail={key: "hunter2"}
    )
    await session.flush()

    row = (await _rows(session))[0]
    assert "hunter2" not in str(row.detail)
    assert row.detail[key] == "[redacted]", "the key should survive so the shape is still readable"


def test_scrubbing_reaches_nested_structures() -> None:
    scrubbed = scrub(
        {
            "email": "a@b.com",
            "credentials": {"password": "hunter2", "nested": [{"api_key": "sk-live-1"}]},
            "safe_list": ["one", "two"],
        }
    )

    assert "hunter2" not in str(scrubbed)
    assert "sk-live-1" not in str(scrubbed)
    assert scrubbed["email"] == "a@b.com"
    assert scrubbed["safe_list"] == ["one", "two"]


def test_scrubbing_leaves_ordinary_values_alone() -> None:
    detail = {"email": "a@b.com", "count": 3, "ok": True, "missing": None}
    assert scrub(detail) == detail


async def test_audit_rows_are_only_ever_inserted(session: AsyncSession, actor) -> None:
    """Two records of the same action must produce two rows, never an update."""
    await record_audit(session, action="user.login", actor=actor, outcome="success")
    await record_audit(session, action="user.login", actor=actor, outcome="success")
    await session.flush()

    assert len(await _rows(session)) == 2
