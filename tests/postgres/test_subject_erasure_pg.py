"""Erasure against the schema that ships.

This file exists because the bug it pins could not be reproduced anywhere else. SQLite
has foreign keys off by default, so no cascade fires and deleting a user always
"succeeds"; on PostgreSQL, `audit_log.actor_user_id` used ON DELETE SET NULL against a
table whose trigger refuses UPDATE, and erasing anybody who had ever signed in failed
outright.

The other reason is the five tables from Phases 1 and 2 that link by `public_id` with no
foreign key. Relying on cascades leaves every one of them behind, and the leftover rows
still name the person.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.models import (
    AuditLog,
    ChatConversation,
    ChatMessage,
    Membership,
    Organization,
    RefreshToken,
    Role,
    SearchFeedback,
    User,
    UserNewsPreference,
    Watchlist,
)
from procuresignal.privacy.inventory import INVENTORY, ErasureAction, SubjectLink
from procuresignal.privacy.subject import erase_subject
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

NOW = datetime.utcnow()


async def _person(session: AsyncSession, slug: str) -> tuple[User, int]:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(
        public_id=f"user-{slug}",
        email=f"{slug}@example.com",
        password_hash="argon2",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return user, organization.id


async def _activity(session: AsyncSession, user: User, organization_id: int, marker: str) -> None:
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
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=f"hash-{marker}",
            family_id=f"family-{marker}",
            expires_at=NOW + timedelta(days=1),
        )
    )
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
    # The tables with no foreign key at all.
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
        Watchlist(
            public_id=f"wl-{marker}",
            organization_id=organization_id,
            name=f"{marker} tier 1",
            normalized_name=f"{marker} tier 1",
            created_by_user_id=user.id,
        )
    )
    await session.commit()


async def test_a_person_who_has_signed_in_can_be_erased_at_all(
    pg_session: AsyncSession,
) -> None:
    """The bug this task found.

    `audit_log.actor_user_id` referenced `users.id` with ON DELETE SET NULL, and the
    table's trigger refuses UPDATE. Deleting anybody with a single audit row raised
    "audit_log is append-only; UPDATE is not permitted" — which is everybody who has
    ever logged in.
    """

    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")

    receipt = await erase_subject(pg_session, user=user, reason="subject request")

    assert receipt.deleted["users"] == 1
    assert (await pg_session.execute(select(User))).scalars().all() == []


async def test_the_tables_with_no_foreign_key_are_cleared_too(
    pg_session: AsyncSession,
) -> None:
    """Relying on cascades would leave these five behind, still naming the person, and
    the operation would report success."""

    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")

    await erase_subject(pg_session, user=user)

    assert (await pg_session.execute(select(UserNewsPreference))).scalars().all() == []
    assert (await pg_session.execute(select(ChatConversation))).scalars().all() == []
    assert (await pg_session.execute(select(ChatMessage))).scalars().all() == []


async def test_nothing_of_the_subject_survives_in_any_registered_table(
    pg_session: AsyncSession,
) -> None:
    """Checked against the registry rather than a list written here, so a table added
    later is covered by this test the day it is registered."""

    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")
    public_id, user_id = user.public_id, user.id

    await erase_subject(pg_session, user=user)

    for entry in INVENTORY:
        if entry.link is SubjectLink.NONE or entry.erasure is not ErasureAction.DELETE:
            continue
        value = public_id if entry.link is SubjectLink.USER_PUBLIC_ID else user_id
        remaining = await pg_session.scalar(
            text(
                f"SELECT count(*) FROM {entry.table} "  # noqa: S608 - table from the registry
                f"WHERE {entry.link_column} = :value"
            ),
            {"value": value},
        )
        assert remaining == 0, f"{entry.table} still holds the subject"


async def test_another_persons_data_is_untouched(pg_session: AsyncSession) -> None:
    first, first_org = await _person(pg_session, "acme")
    second, second_org = await _person(pg_session, "globex")
    await _activity(pg_session, first, first_org, "acme")
    await _activity(pg_session, second, second_org, "globex")

    await erase_subject(pg_session, user=first)

    surviving = (await pg_session.execute(select(ChatMessage))).scalars().all()
    assert [row.content for row in surviving] == ["globex said something"]
    assert len((await pg_session.execute(select(User))).scalars().all()) == 1


async def test_the_audit_trail_survives_and_the_receipt_says_so(
    pg_session: AsyncSession,
) -> None:
    """The one place erasure is refused. Reporting it as deleted would make the receipt
    a false statement, which is worse than the retention it is covering for."""

    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")

    receipt = await erase_subject(pg_session, user=user)

    assert receipt.retained["audit_log"] == 1
    assert "audit_log" not in receipt.deleted
    entries = (await pg_session.execute(select(AuditLog))).scalars().all()
    assert len(entries) == 1
    # The account is gone; the trail still names who acted.
    assert entries[0].actor_email == "acme@example.com"


async def test_a_colleagues_work_outlives_the_colleague(pg_session: AsyncSession) -> None:
    """A watchlist belongs to the organization and its team still depends on it.
    Deleting it would be an availability failure dressed as a privacy control."""

    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")

    receipt = await erase_subject(pg_session, user=user)

    watchlist = (await pg_session.execute(select(Watchlist))).scalar_one()
    assert watchlist.created_by_user_id is None
    assert receipt.anonymised["watchlists"] == 1


async def test_the_receipt_counts_what_it_claims(pg_session: AsyncSession) -> None:
    user, organization_id = await _person(pg_session, "acme")
    await _activity(pg_session, user, organization_id, "acme")

    receipt = await erase_subject(pg_session, user=user, reason="Article 17 request")

    assert receipt.subject_public_id == "user-acme"
    assert receipt.reason == "Article 17 request"
    assert receipt.deleted["chat_messages"] == 1
    assert receipt.deleted["search_feedback"] == 1
    assert receipt.deleted["refresh_tokens"] == 1


async def test_erasing_somebody_with_no_activity_is_not_an_error(
    pg_session: AsyncSession,
) -> None:
    """An account created and never used. Erasure has to be safe to run against
    whatever state the request happens to find."""

    user, _organization_id = await _person(pg_session, "acme")

    receipt = await erase_subject(pg_session, user=user)

    assert receipt.deleted["users"] == 1
    assert await pg_session.scalar(select(func.count()).select_from(User)) == 0


async def test_the_audit_log_still_refuses_to_be_changed(pg_session: AsyncSession) -> None:
    """Dropping the foreign key must not have weakened the guarantee it was fighting.
    The triggers are what make this table evidence rather than a diary."""

    pg_session.add(AuditLog(action="test.event", outcome="success", detail={}))
    await pg_session.commit()

    with pytest.raises(Exception, match="append-only"):
        await pg_session.execute(text("UPDATE audit_log SET outcome = 'tampered'"))
    await pg_session.rollback()

    with pytest.raises(Exception, match="append-only"):
        await pg_session.execute(text("DELETE FROM audit_log"))
    await pg_session.rollback()
