"""Subject access export.

Article 15 asks for everything held about a person, which makes the interesting failures
the omissions: a table the export forgot looks exactly like a table with nothing in it.
So the export walks the registry rather than a hand-written set of queries, and the test
that matters asserts every registered table appears.

The other half is what must not be in it. An export is a file somebody emails; a password
hash or a session token inside one is a credential leak dressed as compliance.
"""

import json
from datetime import datetime, timedelta

import pytest
from procuresignal.models import (
    AlertRule,
    AuditLog,
    ChatConversation,
    ChatMessage,
    Membership,
    Notification,
    Organization,
    RefreshToken,
    Role,
    SearchFeedback,
    User,
    UserNewsPreference,
)
from procuresignal.privacy.inventory import INVENTORY, SubjectLink
from procuresignal.privacy.subject import REDACTED, export_subject
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime.utcnow()


async def _person(session: AsyncSession, slug: str) -> User:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(
        public_id=f"user-{slug}",
        email=f"{slug}@example.com",
        password_hash="argon2-hash-that-must-not-leave",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return user


async def _fill(session: AsyncSession, user: User, organization_id: int, marker: str) -> None:
    """One row in each shape of table: integer link, public-id link, and the audit log."""

    session.add(
        SearchFeedback(
            organization_id=organization_id,
            user_id=user.id,
            query_text=f"{marker} query",
            query_fingerprint=marker * 10,
            processed_article_id=1,
            rank_position=1,
            signal="click",
            mode="hybrid",
        )
    )
    session.add(
        UserNewsPreference(
            user_id=user.public_id,
            preferred_categories=[marker],
            preferred_suppliers=[],
            preferred_regions=[],
            preferred_signals=[],
            excluded_categories=[],
            excluded_suppliers=[],
            excluded_regions=[],
            excluded_signals=[],
            excluded_topics=[],
            onboarding_completed=True,
        )
    )
    session.add(
        ChatConversation(
            user_id=user.public_id,
            conversation_id=f"conv-{marker}",
            title=f"{marker} conversation",
            last_message_at=NOW,
        )
    )
    session.add(
        ChatMessage(
            user_id=user.public_id,
            conversation_id=f"conv-{marker}",
            role="user",
            content=f"{marker} said something",
        )
    )
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=f"secret-hash-{marker}",
            family_id=f"family-{marker}",
            expires_at=NOW + timedelta(days=1),
        )
    )
    rule = AlertRule(
        public_id=f"rule-{marker}",
        organization_id=organization_id,
        name=f"{marker} rule",
        normalized_name=f"{marker} rule",
        min_severity="high",
        risk_types=[],
        is_enabled=True,
        created_by_user_id=user.id,
    )
    session.add(rule)
    await session.flush()
    session.add(
        Notification(
            public_id=f"note-{marker}",
            organization_id=organization_id,
            alert_rule_id=rule.id,
            risk_event_id=1,
            recipient_user_id=user.id,
            channel="in_app",
            subject=f"{marker} alert",
            body="Something happened.",
            supplier_public_ids=[],
            status="delivered",
            attempts=0,
        )
    )
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=user.id,
            actor_email=user.email,
            action="auth.login",
            outcome="success",
            detail={},
        )
    )
    await session.commit()


async def test_every_table_the_registry_links_to_a_person_appears(
    async_session: AsyncSession,
) -> None:
    """A forgotten table looks exactly like an empty one, so absence is the failure to
    guard against. Walking the registry means a table added in Phase 8 is in the export
    the moment it is registered."""

    user = await _person(async_session, "acme")
    membership = user.id
    await _fill(async_session, user, membership, "acme")

    export = await export_subject(async_session, user=user)

    expected = {entry.table for entry in INVENTORY if entry.link is not SubjectLink.NONE}
    assert set(export.tables) == expected


async def test_both_ways_of_identifying_a_person_are_followed(
    async_session: AsyncSession,
) -> None:
    """Integer foreign keys and public-id strings. An export that handles one shape
    silently returns half a person's data, and the half it returns looks complete."""

    user = await _person(async_session, "acme")
    await _fill(async_session, user, user.id, "acme")

    export = await export_subject(async_session, user=user)

    assert export.tables["search_feedback"], "integer-linked table is empty"
    assert export.tables["chat_messages"], "public-id-linked table is empty"
    assert export.tables["chat_messages"][0]["content"] == "acme said something"


async def test_another_persons_rows_are_never_included(async_session: AsyncSession) -> None:
    first = await _person(async_session, "acme")
    second = await _person(async_session, "globex")
    await _fill(async_session, first, first.id, "acme")
    await _fill(async_session, second, second.id, "globex")

    export = await export_subject(async_session, user=first)

    everything = json.dumps(export.tables)
    assert "acme said something" in everything
    assert "globex" not in everything


async def test_the_audit_entries_about_a_person_are_included(
    async_session: AsyncSession,
) -> None:
    """Erasure will not remove these and the export says so elsewhere, but access and
    erasure are different rights. Hiding the audit rows because they cannot be deleted
    answers a question nobody asked."""

    user = await _person(async_session, "acme")
    await _fill(async_session, user, user.id, "acme")

    export = await export_subject(async_session, user=user)

    assert [row["action"] for row in export.tables["audit_log"]] == ["auth.login"]


async def test_a_password_hash_never_leaves_in_an_export(async_session: AsyncSession) -> None:
    """An export is a file somebody emails. A credential inside one is a leak dressed
    as compliance."""

    user = await _person(async_session, "acme")
    await _fill(async_session, user, user.id, "acme")

    export = await export_subject(async_session, user=user)

    everything = json.dumps(export.tables)
    assert "argon2-hash-that-must-not-leave" not in everything
    assert export.tables["users"][0]["password_hash"] == REDACTED


async def test_a_session_token_never_leaves_either(async_session: AsyncSession) -> None:
    user = await _person(async_session, "acme")
    await _fill(async_session, user, user.id, "acme")

    export = await export_subject(async_session, user=user)

    everything = json.dumps(export.tables)
    assert "secret-hash-acme" not in everything
    assert export.tables["refresh_tokens"][0]["token_hash"] == REDACTED


async def test_the_export_survives_being_written_to_a_file(
    async_session: AsyncSession,
) -> None:
    """Article 20 asks for a machine-readable format. A datetime that will not serialise
    turns the whole deliverable into a stack trace at the moment it is needed."""

    user = await _person(async_session, "acme")
    await _fill(async_session, user, user.id, "acme")

    export = await export_subject(async_session, user=user)

    encoded = json.dumps({"subject": export.subject, "tables": export.tables})
    assert json.loads(encoded)["subject"]["public_id"] == "user-acme"


async def test_the_export_names_who_it_is_about_and_when_it_was_made(
    async_session: AsyncSession,
) -> None:
    user = await _person(async_session, "acme")

    export = await export_subject(async_session, user=user)

    assert export.subject["public_id"] == "user-acme"
    assert export.subject["email"] == "acme@example.com"
    assert export.generated_at is not None


async def test_a_person_with_no_activity_still_gets_an_export(
    async_session: AsyncSession,
) -> None:
    """Empty tables are present and empty rather than missing. "We hold nothing about
    you here" is an answer; a shorter file is an ambiguity."""

    user = await _person(async_session, "acme")

    export = await export_subject(async_session, user=user)

    assert export.tables["chat_messages"] == []
    assert export.tables["users"], "the account itself is always held"


@pytest.mark.parametrize(
    "table", sorted({e.table for e in INVENTORY if e.link is SubjectLink.NONE})
)
def test_tables_with_no_link_are_not_in_the_export_contract(table: str) -> None:
    """Nothing in them identifies a person, so including them would be returning
    somebody else's data in answer to a subject request."""

    linked = {entry.table for entry in INVENTORY if entry.link is not SubjectLink.NONE}

    assert table not in linked
