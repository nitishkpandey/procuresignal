"""News article models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
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

    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    raw_payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_provider_article_id", "provider", "provider_article_id"),
        Index("idx_ingest_hash", "ingest_hash"),
        Index("idx_published_at", "published_at"),
        Index("idx_source_name", "source_name"),
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

    __table_args__ = (
        Index("idx_raw_article_id", "raw_article_id"),
        Index("idx_top_level_category", "top_level_category"),
        Index("idx_signal_score", "signal_score"),
        Index("idx_processed_at", "processed_at"),
    )
