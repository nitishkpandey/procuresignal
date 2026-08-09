"""Tests for the append-only audit writer."""

import pytest
from procuresignal.auth.audit import record_audit, scrub
from procuresignal.models import AuditLog, Membership, Organization, Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import AuthenticatedUser


@pytest.fixture
async def actor(async_session: AsyncSession) -> AuthenticatedUser:
    org = Organization(public_id="org-1", name="Acme", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com")
    async_session.add_all([org, user])
    await async_session.flush()
    async_session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.MEMBER))
    await async_session.flush()
    return AuthenticatedUser(
        id=user.id,
        public_id=user.public_id,
        email=user.email,
        organization_id=org.id,
        organization_public_id=org.public_id,
        role=Role.MEMBER,
    )


async def _rows(async_session: AsyncSession) -> list[AuditLog]:
    return list((await async_session.execute(select(AuditLog))).scalars().all())


async def test_records_the_actor_and_action(async_session: AsyncSession, actor) -> None:
    await record_audit(async_session, action="user.login", actor=actor, outcome="success")
    await async_session.flush()

    row = (await _rows(async_session))[0]
    assert row.action == "user.login"
    assert row.outcome == "success"
    assert row.actor_user_id == actor.id
    assert row.actor_email == "buyer@acme.com"
    assert row.organization_id == actor.organization_id


async def test_records_failures_without_an_actor(async_session: AsyncSession) -> None:
    """A failed login has no authenticated actor but still needs a trail."""
    await record_audit(
        async_session,
        action="user.login",
        actor=None,
        outcome="failure",
        detail={"email": "unknown@acme.com"},
    )
    await async_session.flush()

    row = (await _rows(async_session))[0]
    assert row.actor_user_id is None
    assert row.outcome == "failure"
    assert row.detail == {"email": "unknown@acme.com"}


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "PASSWORD", "token", "refresh_token", "secret", "authorization"],
)
async def test_credentials_are_never_persisted(
    async_session: AsyncSession, actor, key: str
) -> None:
    await record_audit(
        async_session, action="user.login", actor=actor, outcome="success", detail={key: "hunter2"}
    )
    await async_session.flush()

    row = (await _rows(async_session))[0]
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


async def test_audit_rows_are_only_ever_inserted(async_session: AsyncSession, actor) -> None:
    """Two records of the same action must produce two rows, never an update."""
    await record_audit(async_session, action="user.login", actor=actor, outcome="success")
    await record_audit(async_session, action="user.login", actor=actor, outcome="success")
    await async_session.flush()

    assert len(await _rows(async_session)) == 2


@pytest.mark.parametrize(
    "message",
    [
        "auth failed for password=hunter2",
        "connect error: api_key: sk-live-abc123",
        "rejected token=eyJhbGciOi",
        "AUTHORIZATION = Bearer abc",
    ],
)
def test_credentials_quoted_inside_a_message_are_masked(message: str) -> None:
    """The key-based scrubber cannot see these: the secret is in the value.

    Driver and transport errors echo configuration back, and those messages are read
    by whoever is on call and stored in the outbox.
    """
    from procuresignal.auth.audit import redact_secrets_in_text

    redacted = redact_secrets_in_text(message)

    for secret in ("hunter2", "sk-live-abc123", "eyJhbGciOi", "abc"):
        if secret in message:
            assert secret not in redacted
    assert "[redacted]" in redacted


def test_ordinary_messages_are_left_alone() -> None:
    message = "connection refused to postgres:5432 after 3 attempts"

    from procuresignal.auth.audit import redact_secrets_in_text

    assert redact_secrets_in_text(message) == message
