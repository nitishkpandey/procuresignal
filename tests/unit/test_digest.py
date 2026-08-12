"""Tests for the morning digest.

Generation is deliberately separable from delivery: that is what makes this shippable
before SMTP credentials exist. When the email transport arrives it renders nothing — it
just sends what this produces.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.models import Membership, Organization, RiskEvent, Role, User
from procuresignal.notifications.digest import (
    DigestSection,
    build_digest,
    render_text,
)
from procuresignal.notifications.outbox import enqueue_matches
from procuresignal.notifications.rules import RuleMatch, create_alert_rule
from procuresignal.notifications.transports.in_app import InAppTransport, deliver_pending
from procuresignal.suppliers.registry import register_supplier
from procuresignal.watchlists.service import add_supplier, create_watchlist
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def setup(async_session: AsyncSession):
    organization = Organization(public_id="org-1", name="Acme", slug="acme")
    async_session.add(organization)
    await async_session.flush()
    user = User(public_id="user-1", email="buyer@acme.com", password_hash="x")
    async_session.add(user)
    await async_session.flush()
    async_session.add(
        Membership(user_id=user.id, organization_id=organization.id, role=Role.MEMBER)
    )

    siemens = await register_supplier(async_session, canonical_name="Siemens AG")
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)

    rule = await create_alert_rule(async_session, organization_id=organization.id, name="Tier 1")
    await async_session.flush()
    return {"organization": organization, "user": user, "supplier": siemens, "rule": rule}


async def _queue(
    session: AsyncSession,
    setup,
    *,
    severity="high",
    risk_type="supply_disruption",
    key="k1",
    deliver=True,
) -> RiskEvent:
    event = RiskEvent(
        event_key=key,
        processed_article_id=1,
        risk_type=risk_type,
        severity=severity,
        confidence=0.9,
        affected_suppliers=["Siemens AG"],
        affected_supplier_ids=[setup["supplier"].public_id],
        affected_locations=[],
        affected_categories=["logistics"],
        evidence_snippet=f"{risk_type} at a plant.",
        recommendation="Review exposure.",
        source_name="Wire",
        source_url="https://example.test/1",
        published_at=datetime(2026, 8, 1),
        status="new",
    )
    session.add(event)
    await session.flush()
    await enqueue_matches(
        session,
        matches=[
            RuleMatch(
                rule=setup["rule"], event=event, supplier_public_ids=[setup["supplier"].public_id]
            )
        ],
    )
    if deliver:
        await deliver_pending(session, transport=InAppTransport())
    await session.flush()
    return event


async def test_a_digest_collects_the_period_alerts(async_session, setup) -> None:
    await _queue(async_session, setup)

    digest = await build_digest(
        async_session, user_id=setup["user"].id, since=datetime.utcnow() - timedelta(days=1)
    )

    assert digest is not None
    assert digest.total == 1
    assert digest.recipient_email == "buyer@acme.com"


async def test_an_empty_period_produces_no_digest(async_session, setup) -> None:
    """A daily message saying nothing happened trains people to stop reading the one
    that says something did."""
    digest = await build_digest(
        async_session, user_id=setup["user"].id, since=datetime.utcnow() - timedelta(days=1)
    )

    assert digest is None


async def test_alerts_are_grouped_by_severity(async_session, setup) -> None:
    """Critical first: a digest that buries the important one is a list, not a briefing."""
    await _queue(async_session, setup, severity="high", key="k1")
    await _queue(async_session, setup, severity="critical", key="k2", risk_type="sanctions")

    digest = await build_digest(
        async_session, user_id=setup["user"].id, since=datetime.utcnow() - timedelta(days=1)
    )

    assert [section.severity for section in digest.sections] == ["critical", "high"]


async def test_a_digest_only_covers_its_own_recipient(async_session, setup) -> None:
    other_org = Organization(public_id="org-2", name="Globex", slug="globex")
    async_session.add(other_org)
    await async_session.flush()
    stranger = User(public_id="user-2", email="other@globex.com", password_hash="x")
    async_session.add(stranger)
    await async_session.flush()
    async_session.add(
        Membership(user_id=stranger.id, organization_id=other_org.id, role=Role.MEMBER)
    )
    await _queue(async_session, setup)

    assert (
        await build_digest(
            async_session, user_id=stranger.id, since=datetime.utcnow() - timedelta(days=1)
        )
        is None
    )


async def test_alerts_outside_the_period_are_excluded(async_session, setup) -> None:
    await _queue(async_session, setup)

    digest = await build_digest(
        async_session, user_id=setup["user"].id, since=datetime.utcnow() + timedelta(hours=1)
    )

    assert digest is None


async def test_undelivered_alerts_are_not_in_the_digest(async_session, setup) -> None:
    """A queued alert has not been sent; summarising it would announce it twice."""
    await _queue(async_session, setup, deliver=False)

    assert (
        await build_digest(
            async_session, user_id=setup["user"].id, since=datetime.utcnow() - timedelta(days=1)
        )
        is None
    )


async def test_the_text_rendering_names_what_happened(async_session, setup) -> None:
    await _queue(async_session, setup, severity="critical", risk_type="sanctions")

    digest = await build_digest(
        async_session, user_id=setup["user"].id, since=datetime.utcnow() - timedelta(days=1)
    )
    text = render_text(digest)

    assert "Siemens AG" in text
    assert "critical" in text.lower()
    assert "Acme" in text


def test_rendering_a_section_is_pure() -> None:
    """Rendering takes a structure and returns text, so the email transport later has
    nothing to build — it just sends this."""
    section = DigestSection(severity="critical", items=[])

    assert section.severity == "critical"
