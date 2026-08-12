"""Build a period summary of a person's alerts.

Deliberately separate from delivery. Generation is the part that carries product
meaning — what happened, to which suppliers, how badly — and delivery is a transport
detail. Splitting them is what makes this shippable before SMTP credentials exist: when
the email transport arrives it renders nothing, it just sends what this produces.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import AlertRule, Notification, Organization, RiskEvent, User

from .rules import SEVERITY_ORDER


@dataclass(frozen=True)
class DigestItem:
    """One alert, as a reader needs to see it."""

    subject: str
    risk_type: str
    severity: str
    suppliers: list[str]
    recommendation: str
    source_name: str
    source_url: str
    rule_name: str


@dataclass(frozen=True)
class DigestSection:
    """Alerts of one severity."""

    severity: str
    items: list[DigestItem] = field(default_factory=list)


@dataclass(frozen=True)
class Digest:
    """What one person is owed for one period."""

    recipient_email: str
    organization_name: str
    since: datetime
    until: datetime
    sections: list[DigestSection] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(len(section.items) for section in self.sections)


async def build_digest(
    session: AsyncSession, *, user_id: int, since: datetime, until: datetime | None = None
) -> Digest | None:
    """Summarise a person's delivered alerts for a period, or None when there are none.

    Returns None rather than an empty digest: a daily message saying nothing happened
    trains people to stop reading the one that says something did.

    Only delivered alerts. Summarising a queued one would announce it before it was
    sent, and again when the transport caught up.
    """

    ends = until or datetime.utcnow()

    rows = (
        await session.execute(
            select(Notification, RiskEvent, AlertRule, User, Organization)
            .join(RiskEvent, RiskEvent.id == Notification.risk_event_id)
            .join(AlertRule, AlertRule.id == Notification.alert_rule_id)
            .join(User, User.id == Notification.recipient_user_id)
            .join(Organization, Organization.id == Notification.organization_id)
            .where(Notification.recipient_user_id == user_id)
            .where(Notification.status == "delivered")
            .where(Notification.delivered_at >= since)
            .where(Notification.delivered_at <= ends)
            .order_by(Notification.delivered_at)
        )
    ).all()

    if not rows:
        return None

    by_severity: dict[str, list[DigestItem]] = {}
    for notification, event, rule, user, organization in rows:
        by_severity.setdefault(event.severity, []).append(
            DigestItem(
                subject=notification.subject,
                risk_type=event.risk_type,
                severity=event.severity,
                suppliers=list(event.affected_suppliers or []),
                recommendation=event.recommendation,
                source_name=event.source_name,
                source_url=event.source_url,
                rule_name=rule.name,
            )
        )

    # Most severe first. A briefing that buries the critical one under six routine
    # items is a list rather than a briefing.
    ordered = sorted(
        by_severity,
        key=lambda severity: SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else -1,
        reverse=True,
    )

    return Digest(
        recipient_email=rows[0][3].email,
        organization_name=rows[0][4].name,
        since=since,
        until=ends,
        sections=[DigestSection(severity=s, items=by_severity[s]) for s in ordered],
    )


def render_text(digest: Digest) -> str:
    """Plain text for a transport to send.

    Text rather than HTML: it is what a plain-text email part needs, what a chat
    adapter can post, and what remains readable when a client strips markup.
    """

    lines = [
        f"ProcureSignal briefing for {digest.organization_name}",
        f"{digest.total} alert{'s' if digest.total != 1 else ''} "
        f"since {digest.since:%d %b %H:%M}",
        "",
    ]

    for section in digest.sections:
        lines.append(f"{section.severity.upper()} ({len(section.items)})")
        for item in section.items:
            suppliers = ", ".join(item.suppliers) or "unnamed supplier"
            lines.extend(
                [
                    f"  - {suppliers}: {item.risk_type.replace('_', ' ')}",
                    f"    {item.recommendation}",
                    f"    {item.source_name} — {item.source_url}",
                    f"    matched by: {item.rule_name}",
                ]
            )
        lines.append("")

    return "\n".join(lines).strip()
