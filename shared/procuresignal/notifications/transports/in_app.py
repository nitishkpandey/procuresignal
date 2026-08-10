"""In-app delivery, and the drain that runs a transport over the outbox."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Notification

from ..outbox import mark_delivered, mark_failed, pending_notifications
from .base import NotificationTransport

logger = logging.getLogger(__name__)


class InAppTransport:
    """Delivery to the application's own notification feed.

    The row is the notification, so there is nothing to send: marking it delivered is
    the delivery. It exists as a transport anyway so the drain has exactly one shape
    and email does not arrive as a special case.
    """

    name = "in_app"

    async def deliver(self, notification: Notification) -> None:
        del notification


async def deliver_pending(
    session: AsyncSession, *, transport: NotificationTransport, limit: int = 500
) -> int:
    """Attempt every queued notification. Returns how many were delivered.

    One failure does not stop the drain. A single notification a transport chokes on
    would otherwise block every alert queued behind it, which turns one bad row into a
    silent outage.
    """

    delivered = 0
    for notification in await pending_notifications(session, limit=limit):
        try:
            await transport.deliver(notification)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the queue
            logger.warning(
                "could not deliver notification %s over %s",
                notification.public_id,
                transport.name,
            )
            await mark_failed(session, notification, error=exc)
            continue

        await mark_delivered(session, notification)
        delivered += 1

    return delivered
