"""Decide which alert rules a batch of risk events satisfies.

Run after risk events are recorded rather than inside the detector: a slow or broken
rule must never stop an event being stored. Detection and alerting fail independently.
"""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import AlertRule, RiskEvent
from procuresignal.suppliers.normalization import normalize
from procuresignal.watchlists.service import watched_supplier_ids

# Weakest first. A severity the detector emits but this omits would compare as unknown
# and silently never satisfy a threshold, which is an alert that looks configured and
# never fires.
SEVERITY_ORDER: tuple[str, ...] = ("low", "medium", "high", "critical")

_RANK = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}


def meets_severity(event_severity: str, minimum: str) -> bool:
    """Whether an event is at or above a rule's floor.

    An unrecognised event severity is treated as the weakest rather than the strongest:
    guessing high would page somebody about something nobody classified.
    """

    return _RANK.get(event_severity, 0) >= _RANK.get(minimum, 0)


class AlertRuleError(Exception):
    """Base class for rule rejections."""


class DuplicateAlertRuleError(AlertRuleError):
    """This organization already has a rule by that name."""


async def create_alert_rule(
    session: AsyncSession,
    *,
    organization_id: int,
    name: str,
    min_severity: str = "high",
    risk_types: list[str] | None = None,
    created_by_user_id: int | None = None,
) -> AlertRule:
    """Create a rule, deriving the fields callers should not have to remember.

    A factory rather than direct construction, so normalization and validation live in
    one place: the API in the next task and the tests here go through the same door.
    """

    normalized = normalize(name)
    if not normalized:
        raise AlertRuleError("an alert rule needs a name")
    if min_severity not in SEVERITY_ORDER:
        raise AlertRuleError(
            f"{min_severity!r} is not a severity; expected one of {list(SEVERITY_ORDER)}"
        )

    existing = (
        await session.execute(
            select(AlertRule)
            .where(AlertRule.organization_id == organization_id)
            .where(AlertRule.normalized_name == normalized)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateAlertRuleError(f"'{existing.name}' already exists in this organization")

    rule = AlertRule(
        public_id=uuid4().hex,
        organization_id=organization_id,
        name=name.strip(),
        normalized_name=normalized,
        min_severity=min_severity,
        risk_types=sorted(set(risk_types or [])),
        created_by_user_id=created_by_user_id,
    )
    session.add(rule)
    await session.flush()
    return rule


@dataclass(frozen=True)
class RuleMatch:
    """One rule satisfied by one event, and the watched suppliers that caused it."""

    rule: AlertRule
    event: RiskEvent
    supplier_public_ids: list[str]


async def evaluate_rules(session: AsyncSession, *, events: list[RiskEvent]) -> list[RuleMatch]:
    """Match a batch of risk events against every enabled rule.

    Matching is on `affected_supplier_ids`, the canonical identity. Matching the
    free-text `affected_suppliers` would reinherit every spelling miss the supplier
    registry exists to remove — an alert that silently never fires for "Siemens AG"
    because the buyer typed "Siemens".
    """

    if not events:
        return []

    rules = (
        (await session.execute(select(AlertRule).where(AlertRule.is_enabled.is_(True))))
        .scalars()
        .all()
    )
    if not rules:
        return []

    # Watchlists are read once per organization rather than once per rule: several
    # rules commonly share one organization, and evaluation runs over every event.
    watched: dict[int, set[str]] = {}
    for rule in rules:
        if rule.organization_id not in watched:
            watched[rule.organization_id] = await watched_supplier_ids(
                session, organization_id=rule.organization_id
            )

    matches: list[RuleMatch] = []
    for event in events:
        affected = set(event.affected_supplier_ids or [])
        if not affected:
            continue

        for rule in rules:
            if rule.risk_types and event.risk_type not in rule.risk_types:
                continue
            if not meets_severity(event.severity, rule.min_severity):
                continue

            hits = affected & watched.get(rule.organization_id, set())
            if not hits:
                continue

            matches.append(RuleMatch(rule=rule, event=event, supplier_public_ids=sorted(hits)))

    return matches
