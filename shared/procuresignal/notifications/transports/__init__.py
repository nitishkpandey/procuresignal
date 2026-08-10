"""Ways of getting an alert to a person.

One interface, several implementations. In-app ships now; email and chat adapters slot
in behind the same protocol once credentials exist, which is what keeps adding them a
day of work rather than a redesign.
"""

from .base import NotificationTransport
from .in_app import InAppTransport, deliver_pending

__all__ = ["NotificationTransport", "InAppTransport", "deliver_pending"]
