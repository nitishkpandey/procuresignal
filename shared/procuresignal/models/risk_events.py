"""Risk event models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class RiskEvent(BaseModel):
    """A procurement risk detected from a processed article."""

    __tablename__ = "risk_events"

    event_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    processed_article_id: Mapped[int] = mapped_column(nullable=False)

    risk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    affected_suppliers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_locations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    evidence_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)

    __table_args__ = (
        UniqueConstraint("event_key", name="uq_risk_events_event_key"),
        Index("idx_risk_events_processed_article_id", "processed_article_id"),
        Index("idx_risk_events_type_status", "risk_type", "status"),
        Index("idx_risk_events_severity", "severity"),
        Index("idx_risk_events_published_at", "published_at"),
    )
