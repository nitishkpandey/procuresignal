"""How exposed a supplier is, and why.

Deterministic arithmetic over risk events, not a model. Two reasons, both practical
rather than ideological: a buyer has to defend a sourcing decision to their own audit
function, and a number nobody can explain is a number that gets overridden and then
ignored. Every score ships with the events that produced it, ranked by how much each
contributed.

The shape is severity × recency × confidence, summed with diminishing returns:

- **Severity** is the detector's own four-value vocabulary.
- **Recency** decays exponentially with a 14-day half-life, matching how long risk events
  are retained. A half-life longer than retention would leave scores propped up by
  evidence that has already been deleted.
- **Confidence** is the detector's, so a hedged extraction counts for less than a clear
  one.
- **Diminishing returns** because thirty outlets covering one incident is one incident.
  Coverage volume is a property of the news cycle, not of the supplier.

Sanctions are outside all of it. Any active designation puts a supplier in the top band
whatever the arithmetic says, because engaging a designated entity is not a risk to be
weighed against convenience — it is a thing that must not happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.jobs.retention import RetentionPolicy
from procuresignal.models import RiskEvent, Supplier, Watchlist, WatchlistEntry

# The detector's vocabulary, from risk_events.taxonomy. A test pins that these keys
# still cover everything it writes.
SEVERITY_WEIGHTS = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}
# An unrecognised severity lands mid-scale rather than at zero: scoring it zero would
# hide the event entirely, which is the one outcome worse than scoring it imprecisely.
UNKNOWN_SEVERITY_WEIGHT = 0.4

HALF_LIFE_DAYS = 14.0

# Each further event counts for a third of the one above it. The geometric sum is bounded
# at 1/(1-d) times the largest contribution, which is what stops a swarm of medium reports
# from ever reaching a single critical event.
#
# Not 0.5, which was the obvious first choice and is wrong: the normalised score of a
# single event is exactly (1 - d), so a discount of 0.5 caps any one event at 0.5 and puts
# the top band permanently out of reach of one critical event. A supplier that filed for
# bankruptcy yesterday has to be able to read as severe on that alone.
CORROBORATION_DISCOUNT = 0.35
_MAXIMUM_TOTAL = 1.0 / (1.0 - CORROBORATION_DISCOUNT)

SANCTIONS_RISK_TYPE = "sanctions"
TOP_BAND = "severe"
# Ordered strongest first; the first threshold a score clears wins.
BANDS = ((0.50, TOP_BAND), (0.25, "elevated"), (0.05, "low"))
NO_BAND = "none"


@dataclass(frozen=True)
class Driver:
    """One event and what it contributed. A score with hidden inputs cannot be checked."""

    event_key: str
    risk_type: str
    severity: str
    confidence: float
    published_at: datetime
    contribution: float
    evidence_snippet: str
    source_name: str


@dataclass(frozen=True)
class ImpactScore:
    value: float
    band: str
    drivers: list[Driver]


@dataclass(frozen=True)
class SupplierImpact:
    supplier_public_id: str
    supplier_name: str
    score: ImpactScore


def _recency(published_at: datetime, now: datetime) -> float:
    # Clamped at the present. Feeds publish wrong timestamps, and an unclamped future
    # date would decay above 1 and let a typo outrank real news.
    age_days = max(0.0, (now - published_at).total_seconds() / 86_400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _contribution(event: RiskEvent, now: datetime) -> float:
    weight = SEVERITY_WEIGHTS.get((event.severity or "").lower(), UNKNOWN_SEVERITY_WEIGHT)
    confidence = min(1.0, max(0.0, event.confidence))
    return weight * _recency(event.published_at, now) * confidence


def _band(value: float, *, sanctioned: bool) -> str:
    if sanctioned:
        return TOP_BAND
    for threshold, name in BANDS:
        if value >= threshold:
            return name
    return NO_BAND


def score_supplier(events: Sequence[RiskEvent], *, now: datetime) -> ImpactScore:
    """Score one supplier's exposure from the events naming it.

    Contributions are sorted strongest first and discounted geometrically, which makes
    the total the largest value any ordering could produce. That is what keeps the score
    monotone: adding an event can never lower it, so a supplier's number cannot fall as
    more bad news arrives.
    """

    if not events:
        return ImpactScore(value=0.0, band=NO_BAND, drivers=[])

    drivers = sorted(
        (
            Driver(
                event_key=event.event_key,
                risk_type=event.risk_type,
                severity=event.severity,
                confidence=event.confidence,
                published_at=event.published_at,
                contribution=_contribution(event, now),
                evidence_snippet=event.evidence_snippet,
                source_name=event.source_name,
            )
            for event in events
        ),
        # `event_key` breaks ties, so two buyers reading the same supplier on the same
        # day see the same order however the rows arrived.
        key=lambda driver: (-driver.contribution, driver.event_key),
    )

    total = sum(
        driver.contribution * (CORROBORATION_DISCOUNT**position)
        for position, driver in enumerate(drivers)
    )
    value = min(1.0, total / _MAXIMUM_TOTAL)
    sanctioned = any(driver.risk_type == SANCTIONS_RISK_TYPE for driver in drivers)

    return ImpactScore(value=value, band=_band(value, sanctioned=sanctioned), drivers=drivers)


async def _events_by_supplier(
    session: AsyncSession, cutoff: datetime
) -> dict[str, list[RiskEvent]]:
    """Recent events grouped by the canonical suppliers they name.

    Grouped on `affected_supplier_ids`, never on the free-text names beside it: matching
    spelling would reinherit every miss the supplier registry exists to remove.
    """

    events = (
        (await session.execute(select(RiskEvent).where(RiskEvent.published_at >= cutoff)))
        .scalars()
        .all()
    )

    grouped: dict[str, list[RiskEvent]] = {}
    for event in events:
        for public_id in event.affected_supplier_ids or []:
            grouped.setdefault(public_id, []).append(event)
    return grouped


async def supplier_impact(
    session: AsyncSession,
    *,
    supplier_public_id: str,
    now: datetime | None = None,
    days: int | None = None,
) -> SupplierImpact | None:
    """Score one supplier, watched or not.

    Not organization-scoped, because the supplier registry and the risk events behind it
    are global read-only data — the same standing as an article. Restricting this to
    watched suppliers would break the obvious use: checking a supplier's exposure
    *before* deciding whether to watch it.
    """

    reference = now or datetime.utcnow()
    window = RetentionPolicy().risk_event_days if days is None else days

    supplier = (
        await session.execute(
            select(Supplier)
            .where(Supplier.public_id == supplier_public_id)
            .where(Supplier.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if supplier is None:
        return None

    grouped = await _events_by_supplier(session, reference - timedelta(days=window))
    return SupplierImpact(
        supplier_public_id=supplier.public_id,
        supplier_name=supplier.canonical_name,
        score=score_supplier(grouped.get(supplier.public_id, []), now=reference),
    )


async def watched_impact(
    session: AsyncSession,
    *,
    organization_id: int,
    now: datetime | None = None,
    days: int | None = None,
) -> list[SupplierImpact]:
    """Score every supplier this organization watches, most exposed first.

    Two queries and a grouping in memory rather than a JSON containment join per
    supplier. Risk events are pruned after 14 days, so the window is small, and matching
    in Python keeps this dialect-free — `affected_supplier_ids` is a JSON array whose
    containment operator differs between SQLite and PostgreSQL.
    """

    reference = now or datetime.utcnow()
    window = RetentionPolicy().risk_event_days if days is None else days
    cutoff = reference - timedelta(days=window)

    suppliers = (
        (
            await session.execute(
                select(Supplier)
                .join(WatchlistEntry, WatchlistEntry.supplier_id == Supplier.id)
                .join(Watchlist, Watchlist.id == WatchlistEntry.watchlist_id)
                .where(Watchlist.organization_id == organization_id)
                .where(Supplier.is_active.is_(True))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not suppliers:
        return []

    by_supplier = await _events_by_supplier(session, cutoff)

    impacts = [
        SupplierImpact(
            supplier_public_id=supplier.public_id,
            supplier_name=supplier.canonical_name,
            score=score_supplier(by_supplier.get(supplier.public_id, []), now=reference),
        )
        for supplier in suppliers
    ]
    impacts.sort(key=lambda impact: (-impact.score.value, impact.supplier_name))
    return impacts
