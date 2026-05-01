"""Pipeline execution and matching models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class NewsPipelineRun(BaseModel):
    """Record of each pipeline execution (for observability)."""

    __tablename__ = "news_pipeline_runs"

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)

    articles_fetched: Mapped[int] = mapped_column(Integer, default=0)
    articles_kept: Mapped[int] = mapped_column(Integer, default=0)
    articles_rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    articles_sent_to_llm: Mapped[int] = mapped_column(Integer, default=0)
    feeds_materialized: Mapped[int] = mapped_column(Integer, default=0)

    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_pipeline_runs_status", "status"),
        Index("idx_pipeline_runs_started_at", "started_at"),
    )


class NewsArticleMatch(BaseModel):
    """Why an article matched a user (detailed matching logic)."""

    __tablename__ = "news_article_matches"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_article_id: Mapped[int] = mapped_column(nullable=False)

    matched_supplier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    matched_region: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    matched_category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    matched_event_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    match_score: Mapped[float] = mapped_column(nullable=False)
    reason_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("idx_user_article", "user_id", "processed_article_id"),
        Index("idx_matched_supplier", "matched_supplier"),
    )


class NewsPriorityEvent(BaseModel):
    """Priority signals (bankruptcy, M&A) for fast-lane processing."""

    __tablename__ = "news_priority_events"

    processed_article_id: Mapped[int] = mapped_column(nullable=False)

    priority_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    dispatch_window: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_priority_type", "priority_type"),
        Index("idx_priority_events_status", "status"),
    )
