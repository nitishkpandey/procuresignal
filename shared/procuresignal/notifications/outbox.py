"""The notification outbox.

Evaluation writes rows here and returns; a separate drain delivers them. That split is
what makes delivery at-least-once — a transport outage retries from the table rather
than losing the alert — and stops a slow transport stalling the rules that produced it.

A missed disruption alert is the failure this product exists to prevent. A duplicate is
an annoyance. Everything here is shaped by that asymmetry.
"""

import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.auth.audit import redact_secrets_in_text
from procuresignal.models import Membership, Notification, User

from .rules import RuleMatch

logger = logging.getLogger(__name__)

# Beyond this a transport is broken rather than briefly unavailable, and retrying
# forever would hide that behind a queue that never drains.
MAX_DELIVERY_ATTEMPTS = 5

IN_APP = "in_app"

_ERROR_LIMIT = 2000


async def recipients_for(session: AsyncSession, *, organization_id: int) -> list[User]:
    """Everyone in the organization.

    Per-user routing preferences are a later refinement; sending the team's alert to
    the team is the behaviour that matches how watchlists are scoped.
    """

    return list(
        (
            await session.execute(
                select(User)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.organization_id == organization_id)
                .where(User.is_active.is_(True))
                .order_by(User.id)
            )
        )
        .scalars()
        .all()
    )


def _subject(match: RuleMatch) -> str:
    suppliers = ", ".join(match.supplier_public_ids)
    names = ", ".join(match.event.affected_suppliers or []) or suppliers
    return f"{match.event.severity.title()} {match.event.risk_type.replace('_', ' ')}: {names}"[
        :300
    ]


def _body(match: RuleMatch) -> str:
    event = match.event
    return "\n".join(
        [
            event.evidence_snippet or "",
            "",
            f"Recommended action: {event.recommendation}",
            f"Source: {event.source_name}",
            f"Matched rule: {match.rule.name}",
        ]
    ).strip()


async def enqueue_matches(session: AsyncSession, *, matches: list[RuleMatch]) -> int:
    """Queue one notification per recipient per match. Returns how many were created.

    Re-queuing an existing one is skipped rather than treated as an error: evaluation
    runs on a schedule and sees the same event repeatedly, which is normal.
    """

    if not matches:
        return 0

    created = 0
    recipients: dict[int, list[User]] = {}

    for match in matches:
        organization_id = match.rule.organization_id
        if organization_id not in recipients:
            recipients[organization_id] = await recipients_for(
                session, organization_id=organization_id
            )

        for user in recipients[organization_id]:
            existing = (
                await session.execute(
                    select(Notification.id)
                    .where(Notification.alert_rule_id == match.rule.id)
                    .where(Notification.risk_event_id == match.event.id)
                    .where(Notification.recipient_user_id == user.id)
                    .where(Notification.channel == IN_APP)
                )
            ).first()
            if existing is not None:
                continue

            session.add(
                Notification(
                    public_id=uuid4().hex,
                    organization_id=organization_id,
                    alert_rule_id=match.rule.id,
                    risk_event_id=match.event.id,
                    recipient_user_id=user.id,
                    channel=IN_APP,
                    subject=_subject(match),
                    body=_body(match),
                    supplier_public_ids=list(match.supplier_public_ids),
                )
            )
            created += 1

    await session.flush()
    return created


async def pending_notifications(session: AsyncSession, *, limit: int = 500) -> list[Notification]:
    """Notifications still owed, oldest first."""

    return list(
        (
            await session.execute(
                select(Notification)
                .where(Notification.status == "pending")
                .order_by(Notification.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def mark_delivered(session: AsyncSession, notification: Notification) -> None:
    notification.status = "delivered"
    notification.delivered_at = datetime.utcnow()
    notification.last_error = None
    await session.flush()


async def mark_failed(
    session: AsyncSession, notification: Notification, *, error: BaseException
) -> None:
    """Record a failed attempt, keeping the notification queued until it gives up.

    The message has inline credentials masked: transport errors quote configuration
    back at you, and whoever is on call reads these. The key-based scrubber cannot
    help here, because the secret is inside the message rather than under a key.
    """

    notification.attempts += 1
    notification.last_error = redact_secrets_in_text(str(error))[:_ERROR_LIMIT]
    if notification.attempts >= MAX_DELIVERY_ATTEMPTS:
        notification.status = "failed"
        logger.error(
            "giving up on notification %s after %s attempts",
            notification.public_id,
            notification.attempts,
        )
    await session.flush()
