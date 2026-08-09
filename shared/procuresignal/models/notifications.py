"""Alert rules and the notification outbox."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AlertRule(BaseModel):
    """When to tell an organization about a risk event.

    Scoped to the organization, like the watchlists it reads. A rule matches only
    suppliers that organization watches, so alerting stays about their exposure rather
    than about everything the pipeline finds.
    """

    __tablename__ = "alert_rules"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Inclusive floor: a critical event satisfies a rule set to high.
    min_severity: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    # Empty means every type. An explicit list of all of them would go stale the moment
    # the taxonomy gains one.
    risk_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_name", name="uq_alert_rule_org_name"),
        Index("idx_alert_rule_organization", "organization_id"),
    )


class Notification(BaseModel):
    """One alert owed to one person.

    An outbox rather than direct delivery. Evaluation writes a row and returns; a
    separate drain sends it. That is what makes delivery at-least-once — a transport
    outage retries from here rather than losing the alert — and it keeps a slow or
    broken transport from stalling the rule that produced it.
    """

    __tablename__ = "notifications"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    alert_rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    risk_event_id: Mapped[int] = mapped_column(
        ForeignKey("risk_events.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[str] = mapped_column(String(20), default="in_app", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Which watched suppliers caused this. An alert a buyer cannot trace back to a
    # supplier and a rule is one they learn to ignore.
    supplier_public_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # The idempotency key. Rules are evaluated on a schedule and see the same event
        # repeatedly, so this is what stops a re-run re-notifying — enforced by the
        # database rather than by a query-then-insert that races itself.
        UniqueConstraint(
            "alert_rule_id",
            "risk_event_id",
            "recipient_user_id",
            "channel",
            name="uq_notification_idempotency",
        ),
        Index("idx_notification_recipient", "recipient_user_id", "read_at"),
        Index("idx_notification_status", "status"),
    )
