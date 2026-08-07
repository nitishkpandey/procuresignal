"""Alert rules."""

from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, UniqueConstraint
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
