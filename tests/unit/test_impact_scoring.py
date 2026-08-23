"""Supplier impact scoring.

Assertions here are properties, not magic constants: more severe never scores lower,
older never scores higher, adding an event never lowers the total. Pinning the arithmetic
to specific numbers would mean every weight change rewrites the suite, and the weights are
meant to be tunable — what must not change is the direction each input pushes the score.

The one exception is the sanctions floor, which is pinned exactly, because it is a
compliance stop rather than a point on a gradient.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.models import RiskEvent
from procuresignal.scoring.impact import (
    HALF_LIFE_DAYS,
    SEVERITY_WEIGHTS,
    TOP_BAND,
    score_supplier,
)

NOW = datetime(2026, 8, 23, 12, 0, 0)


def _event(
    *,
    severity: str = "medium",
    risk_type: str = "strike",
    confidence: float = 1.0,
    age_days: float = 0.0,
    key: str = "event",
) -> RiskEvent:
    return RiskEvent(
        event_key=key,
        processed_article_id=1,
        risk_type=risk_type,
        severity=severity,
        confidence=confidence,
        affected_suppliers=[],
        affected_supplier_ids=[],
        affected_locations=[],
        affected_categories=[],
        evidence_snippet="Evidence.",
        recommendation="Do something.",
        source_name="Reuters",
        published_at=NOW - timedelta(days=age_days),
        status="new",
    )


def test_no_events_is_no_exposure() -> None:
    """A supplier nobody has reported anything about scores zero, not a small
    positive number that looks like faint smoke."""

    score = score_supplier([], now=NOW)

    assert score.value == 0.0
    assert score.band == "none"
    assert score.drivers == []


@pytest.mark.parametrize(
    "weaker,stronger",
    [("low", "medium"), ("medium", "high"), ("high", "critical")],
)
def test_a_more_severe_event_never_scores_lower(weaker: str, stronger: str) -> None:
    weak = score_supplier([_event(severity=weaker)], now=NOW)
    strong = score_supplier([_event(severity=stronger)], now=NOW)

    assert strong.value > weak.value


@pytest.mark.parametrize("age_days", [1, 7, 14, 30])
def test_an_older_event_never_scores_higher(age_days: int) -> None:
    """Recency decay is the reason a supplier's score falls back on its own once the
    news stops, without anyone clearing a flag."""

    fresh = score_supplier([_event(age_days=0)], now=NOW)
    stale = score_supplier([_event(age_days=age_days)], now=NOW)

    assert stale.value < fresh.value


def test_the_half_life_is_what_it_claims() -> None:
    """Fourteen days, matching the risk-event retention window. A half-life longer than
    retention would mean scores that never fully decay because the evidence is deleted
    while it still counts."""

    fresh = score_supplier([_event(age_days=0)], now=NOW)
    aged = score_supplier([_event(age_days=HALF_LIFE_DAYS)], now=NOW)

    assert aged.value == pytest.approx(fresh.value / 2, rel=1e-6)


def test_lower_confidence_scores_lower() -> None:
    certain = score_supplier([_event(confidence=1.0)], now=NOW)
    unsure = score_supplier([_event(confidence=0.5)], now=NOW)

    assert unsure.value < certain.value


def test_adding_an_event_never_lowers_the_score() -> None:
    """Monotonic in the evidence. A score that could fall when more bad news arrives is
    one nobody would trust twice."""

    events = [_event(key="a", severity="high")]
    running = score_supplier(events, now=NOW).value

    for index, severity in enumerate(["low", "critical", "medium", "low", "high"]):
        events.append(_event(key=f"extra-{index}", severity=severity, age_days=index))
        current = score_supplier(events, now=NOW).value
        assert current >= running
        running = current


def test_a_pile_of_medium_reports_cannot_outrank_one_critical() -> None:
    """The reason the sum has diminishing returns.

    Thirty outlets covering one medium incident is one incident, not thirty. Without
    discounting, well-covered minor news buries a single critical event — and coverage
    volume is a property of the news cycle, not of the supplier's risk.
    """

    swarm = [_event(key=f"medium-{index}", severity="medium") for index in range(30)]

    assert (
        score_supplier(swarm, now=NOW).value
        < score_supplier([_event(severity="critical")], now=NOW).value
    )


def test_one_critical_event_is_enough_to_reach_the_top_band() -> None:
    """A supplier that filed for bankruptcy yesterday is severe on that alone. Waiting
    for a second source before showing red defeats the point of early warning.

    This is a calibration guard, not arithmetic trivia. The normalised score of a single
    event is exactly `1 - CORROBORATION_DISCOUNT`, so a discount of 0.5 — the obvious
    first choice, and what this was written with — caps any one event at 0.5 and puts the
    top band permanently out of reach of one event however bad it is. The scenario read
    `elevated` until the discount was changed.
    """

    alone = score_supplier([_event(severity="critical", confidence=1.0, age_days=0)], now=NOW)

    assert alone.band == TOP_BAND


def test_a_single_medium_event_does_not_reach_the_top_band() -> None:
    """The other side of the same calibration: loosening the discount until one
    critical event reads severe must not drag ordinary news up with it."""

    alone = score_supplier([_event(severity="medium", confidence=1.0, age_days=0)], now=NOW)

    assert alone.band != TOP_BAND


def test_the_score_stays_within_its_range() -> None:
    """Bounded so a band threshold means something and the UI can render it."""

    everything = [_event(key=f"e-{index}", severity="critical") for index in range(50)]
    score = score_supplier(everything, now=NOW)

    assert 0.0 <= score.value <= 1.0


def test_an_active_sanctions_match_forces_the_top_band() -> None:
    """A compliance stop, not a point on a gradient. One low-confidence sanctions event
    outranks any amount of ordinary bad news, because engaging a designated entity is
    not a risk to weigh — it is a thing that must not happen.
    """

    sanctioned = score_supplier(
        [_event(risk_type="sanctions", severity="low", confidence=0.1, age_days=13)],
        now=NOW,
    )

    assert sanctioned.band == TOP_BAND


def test_the_sanctions_floor_lifts_the_band_without_faking_the_number() -> None:
    """The value stays the honest arithmetic. Inflating it too would make one stale
    designation look like more news than it is, and the drivers would not add up.
    """

    events = [_event(risk_type="sanctions", severity="low", confidence=0.1, age_days=13)]
    score = score_supplier(events, now=NOW)

    assert score.band == TOP_BAND
    assert score.value < 0.1
    assert score.drivers[0].risk_type == "sanctions"


def test_drivers_explain_the_number_in_order_of_contribution() -> None:
    """A procurement decision defended with an unexplainable number is not defensible.
    The buyer has to be able to say which events produced it, biggest first."""

    events = [
        _event(key="stale-medium", severity="medium", age_days=20),
        _event(key="fresh-critical", severity="critical", age_days=0),
        _event(key="fresh-low", severity="low", age_days=0),
    ]

    drivers = score_supplier(events, now=NOW).drivers

    assert [driver.event_key for driver in drivers] == [
        "fresh-critical",
        "fresh-low",
        "stale-medium",
    ]
    assert all(
        drivers[index].contribution >= drivers[index + 1].contribution
        for index in range(len(drivers) - 1)
    )


def test_every_event_appears_as_a_driver() -> None:
    """A score with hidden inputs is one nobody can check."""

    events = [_event(key=f"e-{index}") for index in range(5)]

    assert len(score_supplier(events, now=NOW).drivers) == 5


def test_scoring_is_deterministic() -> None:
    """Two buyers reading the same supplier on the same day must see the same number,
    including when contributions tie."""

    events = [_event(key=f"tied-{index}") for index in range(6)]

    first = score_supplier(events, now=NOW)
    second = score_supplier(list(reversed(events)), now=NOW)

    assert first.value == second.value
    assert [d.event_key for d in first.drivers] == [d.event_key for d in second.drivers]


def test_bands_rise_with_the_score() -> None:
    quiet = score_supplier([_event(severity="low", age_days=13)], now=NOW)
    busy = score_supplier(
        [_event(key=f"c-{index}", severity="critical") for index in range(4)], now=NOW
    )

    assert quiet.band != busy.band
    assert quiet.value < busy.value


def test_an_event_dated_in_the_future_does_not_score_above_a_fresh_one() -> None:
    """Feeds publish wrong timestamps. Left unclamped, a date a week out would inflate
    the decay above 1 and let a bad timestamp outrank real news."""

    fresh = score_supplier([_event(age_days=0)], now=NOW)
    future = score_supplier([_event(age_days=-7)], now=NOW)

    assert future.value == pytest.approx(fresh.value)


def test_an_unknown_severity_still_counts() -> None:
    """A severity nobody in this codebase writes today should not silently score zero
    and hide the event; it should land in the middle and be visible in the drivers."""

    unknown = score_supplier([_event(severity="catastrophic")], now=NOW)

    assert unknown.value > 0
    assert unknown.drivers[0].severity == "catastrophic"


def test_the_severity_vocabulary_matches_the_risk_taxonomy() -> None:
    """The detector only ever writes these four. A weight table with different keys
    would score every real event as unknown."""

    from procuresignal.risk_events.taxonomy import SEVERITY_BY_RISK_TYPE

    assert set(SEVERITY_BY_RISK_TYPE.values()) <= set(SEVERITY_WEIGHTS)
