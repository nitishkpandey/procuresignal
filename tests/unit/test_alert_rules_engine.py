"""Tests for alert rule evaluation.

A rule says: for this organization, when a risk event touches a supplier we watch, at
or above this severity, of these kinds, tell these people.

Matching is on RiskEvent.affected_supplier_ids — the canonical identity Phase 2 added.
Matching the free-text affected_suppliers instead would reinherit exactly the misses
that work removed, which is the failure mode worth guarding hardest here.
"""

from datetime import datetime

import pytest
from procuresignal.models import (
    AlertRule,
    Membership,
    Organization,
    RiskEvent,
    Role,
    User,
)
from procuresignal.notifications.rules import (
    SEVERITY_ORDER,
    create_alert_rule,
    evaluate_rules,
)
from procuresignal.suppliers.registry import register_supplier
from procuresignal.watchlists.service import add_supplier, create_watchlist
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def setup(async_session: AsyncSession):
    organization = Organization(public_id="org-1", name="Acme", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com", password_hash="x")
    async_session.add_all([organization, user])
    await async_session.flush()
    async_session.add(
        Membership(user_id=user.id, organization_id=organization.id, role=Role.MEMBER)
    )

    siemens = await register_supplier(async_session, canonical_name="Siemens AG")
    bosch = await register_supplier(async_session, canonical_name="Robert Bosch GmbH")

    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await async_session.flush()

    return {
        "organization": organization,
        "user": user,
        "watched": siemens,
        "unwatched": bosch,
    }


def _event(**overrides) -> RiskEvent:
    defaults = dict(
        event_key="k1",
        processed_article_id=1,
        risk_type="supply_disruption",
        severity="high",
        confidence=0.9,
        affected_suppliers=["Siemens AG"],
        affected_supplier_ids=[],
        affected_locations=[],
        affected_categories=["logistics"],
        evidence_snippet="A plant halted.",
        recommendation="Review exposure.",
        source_name="Wire",
        source_url="https://example.test/1",
        published_at=datetime(2026, 8, 1),
        status="new",
    )
    defaults.update(overrides)
    return RiskEvent(**defaults)


async def _rule(session: AsyncSession, organization, **overrides) -> AlertRule:
    enabled = overrides.pop("is_enabled", True)
    overrides.pop("public_id", None)
    defaults = dict(name="Tier 1 disruptions", min_severity="high", risk_types=[])
    defaults.update(overrides)

    rule = await create_alert_rule(session, organization_id=organization.id, **defaults)
    rule.is_enabled = enabled
    await session.flush()
    return rule


async def test_a_watched_supplier_at_severity_matches(async_session, setup) -> None:
    await _rule(async_session, setup["organization"])
    event = _event(affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    matches = await evaluate_rules(async_session, events=[event])

    assert [m.rule.name for m in matches] == ["Tier 1 disruptions"]
    assert matches[0].supplier_public_ids == [setup["watched"].public_id]


async def test_an_unwatched_supplier_does_not_match(async_session, setup) -> None:
    """Alerting on everything is the same as alerting on nothing."""
    await _rule(async_session, setup["organization"])
    event = _event(affected_supplier_ids=[setup["unwatched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_matching_uses_identity_not_free_text(async_session, setup) -> None:
    """The event names the supplier in text but resolved to nothing.

    Matching the text would reinherit every spelling miss Phase 2 removed.
    """
    await _rule(async_session, setup["organization"])
    event = _event(affected_suppliers=["Siemens AG"], affected_supplier_ids=[])
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_severity_below_the_threshold_does_not_match(async_session, setup) -> None:
    await _rule(async_session, setup["organization"], min_severity="critical")
    event = _event(severity="high", affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_severity_above_the_threshold_matches(async_session, setup) -> None:
    """At or above, not equal to: a critical event must satisfy a high threshold."""
    await _rule(async_session, setup["organization"], min_severity="high")
    event = _event(severity="critical", affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert len(await evaluate_rules(async_session, events=[event])) == 1


async def test_an_empty_risk_type_list_means_every_type(async_session, setup) -> None:
    await _rule(async_session, setup["organization"], risk_types=[])
    event = _event(risk_type="sanctions", affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert len(await evaluate_rules(async_session, events=[event])) == 1


async def test_a_risk_type_filter_excludes_other_types(async_session, setup) -> None:
    await _rule(async_session, setup["organization"], risk_types=["sanctions"])
    event = _event(
        risk_type="supply_disruption", affected_supplier_ids=[setup["watched"].public_id]
    )
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_a_disabled_rule_never_matches(async_session, setup) -> None:
    await _rule(async_session, setup["organization"], is_enabled=False)
    event = _event(affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_another_organizations_rule_does_not_match_our_event(async_session, setup) -> None:
    """Rules and watchlists are both tenant-scoped; a match needs both to line up."""
    other = Organization(public_id="org-2", name="Globex", slug="globex")
    async_session.add(other)
    await async_session.flush()
    await _rule(async_session, other, public_id="rule-2")

    event = _event(affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert await evaluate_rules(async_session, events=[event]) == []


async def test_one_event_can_satisfy_several_rules(async_session, setup) -> None:
    await _rule(async_session, setup["organization"], public_id="rule-a", name="All")
    await _rule(
        async_session,
        setup["organization"],
        public_id="rule-b",
        name="Disruptions only",
        risk_types=["supply_disruption"],
    )
    event = _event(affected_supplier_ids=[setup["watched"].public_id])
    async_session.add(event)
    await async_session.flush()

    assert {m.rule.name for m in await evaluate_rules(async_session, events=[event])} == {
        "All",
        "Disruptions only",
    }


async def test_evaluating_no_events_touches_nothing(async_session, setup) -> None:
    assert await evaluate_rules(async_session, events=[]) == []


def test_severity_order_covers_what_the_detector_emits() -> None:
    """A severity the detector produces but the order omits would sort as unknown and
    silently never satisfy a threshold."""
    assert {"medium", "high", "critical"} <= set(SEVERITY_ORDER)
