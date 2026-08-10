"""The transport contract."""

from typing import Protocol

from procuresignal.models import Notification


class NotificationTransport(Protocol):
    """Delivers one notification, or raises.

    Raising is the correct failure: the outbox counts the attempt and keeps the
    notification queued. A transport that swallows its own errors would silently
    convert at-least-once delivery into at-most-once.
    """

    name: str

    async def deliver(self, notification: Notification) -> None: ...
