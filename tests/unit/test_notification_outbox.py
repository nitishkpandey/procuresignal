"""Tests for the notification outbox.

At-least-once, never at-most-once. A missed disruption alert is the failure this
product exists to prevent; a duplicate is an annoyance. So delivery retries, and
duplicates are stopped by a constraint rather than by a query-then-insert race.
"""

from datetime import datetime

import pytest
from procuresignal.models import (
    Membership,
    Notification,
    Organization,
    RiskEvent,
    Role,
    User,
)
from procuresignal.notifications.outbox import (
    enqueue_matches,
    mark_delivered,
    mark_failed,
    pending_notifications,
    recipients_for,
)
from procuresignal.notifications.rules import RuleMatch, create_alert_rule
from procuresignal.suppliers.registry import register_supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def setup(async_session: AsyncSession):
    organization = Organization(public_id="org-1", name="Acme", slug="acme")
    async_session.add(organization)
    await async_session.flush()

    members = []
    for index, (email, role) in enumerate(
        [("buyer@acme.com", Role.MEMBER), ("boss@acme.com", Role.OWNER)], start=1
    ):
        user = User(public_id=f"user-{index}", email=email, password_hash="x")
        async_session.add(user)
        await async_session.flush()
        async_session.add(Membership(user_id=user.id, organization_id=organization.id, role=role))
        members.append(user)

    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    rule = await create_alert_rule(async_session, organization_id=organization.id, name="Tier 1")

    event = RiskEvent(
        event_key="k1",
        processed_article_id=1,
        risk_type="supply_disruption",
        severity="high",
        confidence=0.9,
        affected_suppliers=["Siemens AG"],
        affected_supplier_ids=[supplier.public_id],
        affected_locations=[],
        affected_categories=["logistics"],
        evidence_snippet="A plant halted.",
        recommendation="Review exposure.",
        source_name="Wire",
        source_url="https://example.test/1",
        published_at=datetime(2026, 8, 1),
        status="new",
    )
    async_session.add(event)
    await async_session.flush()

    return {
        "organization": organization,
        "members": members,
        "rule": rule,
        "event": event,
        "supplier": supplier,
    }


def _match(setup) -> RuleMatch:
    return RuleMatch(
        rule=setup["rule"],
        event=setup["event"],
        supplier_public_ids=[setup["supplier"].public_id],
    )


async def _rows(session: AsyncSession) -> list[Notification]:
    return list((await session.execute(select(Notification))).scalars().all())


async def test_every_member_of_the_organization_is_a_recipient(async_session, setup) -> None:
    recipients = await recipients_for(async_session, organization_id=setup["organization"].id)

    assert {u.email for u in recipients} == {"buyer@acme.com", "boss@acme.com"}


async def test_a_match_produces_one_notification_per_recipient(async_session, setup) -> None:
    created = await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()

    assert created == 2
    assert len(await _rows(async_session)) == 2


async def test_re_evaluating_the_same_event_does_not_re_notify(async_session, setup) -> None:
    """Rules are evaluated on a schedule, so the same event is seen repeatedly."""
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    created = await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()

    assert created == 0
    assert len(await _rows(async_session)) == 2


async def test_a_notification_records_why_it_was_sent(async_session, setup) -> None:
    """An alert a buyer cannot trace back is one they learn to ignore."""
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()

    notification = (await _rows(async_session))[0]
    assert notification.alert_rule_id == setup["rule"].id
    assert notification.risk_event_id == setup["event"].id
    assert notification.supplier_public_ids == [setup["supplier"].public_id]
    assert "Siemens AG" in notification.subject


async def test_new_notifications_start_pending(async_session, setup) -> None:
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()

    notification = (await _rows(async_session))[0]
    assert notification.status == "pending"
    assert notification.attempts == 0
    assert notification.delivered_at is None


async def test_pending_returns_only_undelivered(async_session, setup) -> None:
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    first, second = await _rows(async_session)

    await mark_delivered(async_session, first)
    await async_session.flush()

    pending = await pending_notifications(async_session)
    assert [n.id for n in pending] == [second.id]


async def test_delivery_records_when_it_happened(async_session, setup) -> None:
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    notification = (await _rows(async_session))[0]

    await mark_delivered(async_session, notification)
    await async_session.flush()

    assert notification.status == "delivered"
    assert notification.delivered_at is not None


async def test_a_failure_stays_pending_and_counts_the_attempt(async_session, setup) -> None:
    """At-least-once: a transport failure must be retried, not discarded."""
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    notification = (await _rows(async_session))[0]

    await mark_failed(async_session, notification, error=RuntimeError("smtp refused"))
    await async_session.flush()

    assert notification.status == "pending"
    assert notification.attempts == 1
    assert "smtp refused" in notification.last_error
    assert notification in await pending_notifications(async_session)


async def test_a_notification_gives_up_after_enough_attempts(async_session, setup) -> None:
    """Retrying forever would hide a transport that is simply broken."""
    from procuresignal.notifications.outbox import MAX_DELIVERY_ATTEMPTS

    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    notification = (await _rows(async_session))[0]

    for _ in range(MAX_DELIVERY_ATTEMPTS):
        await mark_failed(async_session, notification, error=RuntimeError("down"))
    await async_session.flush()

    assert notification.status == "failed"
    assert notification not in await pending_notifications(async_session)


async def test_the_error_is_scrubbed_of_credentials(async_session, setup) -> None:
    """Transport errors quote configuration, and on-call reads these."""
    await enqueue_matches(async_session, matches=[_match(setup)])
    await async_session.flush()
    notification = (await _rows(async_session))[0]

    await mark_failed(
        async_session,
        notification,
        error=RuntimeError("auth failed for password=hunter2"),
    )
    await async_session.flush()

    assert "hunter2" not in notification.last_error


async def test_enqueueing_nothing_is_not_an_error(async_session, setup) -> None:
    assert await enqueue_matches(async_session, matches=[]) == 0
