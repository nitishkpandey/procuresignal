"""News article models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class NewsArticleRaw(BaseModel):
    """Raw articles fetched from news APIs (before filtering)."""

    __tablename__ = "news_articles_raw"

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_article_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    query_group: Mapped[str] = mapped_column(String(100), nullable=False)
    ingest_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    article_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_domains: Mapped[Optional[list]] = mapped_column(JSON, default=list, nullable=True)
    source_countries: Mapped[Optional[list]] = mapped_column(JSON, default=list, nullable=True)
    registry_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source_published_at_raw: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    raw_payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    enrichment_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    enrichment_attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    enrichment_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enrichment_lease_owner: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    enrichment_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_provider_article_id", "provider", "provider_article_id"),
        Index("idx_ingest_hash", "ingest_hash"),
        Index("idx_published_at", "published_at"),
        Index("idx_source_name", "source_name"),
        Index("idx_raw_source_id", "source_id"),
        Index("idx_raw_enrichment_lifecycle", "enrichment_status", "enrichment_next_attempt_at"),
        Index("idx_raw_enrichment_lease", "enrichment_lease_expires_at", "enrichment_lease_owner"),
    )


class NewsArticleProcessed(BaseModel):
    """Processed articles after enrichment (summaries, categories, signals)."""

    __tablename__ = "news_articles_processed"

    raw_article_id: Mapped[int] = mapped_column(nullable=False)

    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    top_level_category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    signal_tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    priority_signal: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    detected_regions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    detected_suppliers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    detected_categories: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    signal_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(20),
        default="completed",
        nullable=False,
    )

    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    risk_event_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enrichment_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    enrichment_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    enrichment_policy_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deterministic_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_used: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("raw_article_id", name="uq_news_articles_processed_raw_article_id"),
        Index("idx_raw_article_id", "raw_article_id"),
        Index("idx_top_level_category", "top_level_category"),
        Index("idx_signal_score", "signal_score"),
        Index("idx_processed_at", "processed_at"),
        Index("idx_risk_event_scan_pending", "risk_event_checked_at", "processed_at"),
    )
