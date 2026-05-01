"""User preferences and news feed models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class UserNewsPreference(BaseModel):
    """User's news preferences (what they want to see)."""

    __tablename__ = "user_news_preferences"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    preferred_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preferred_suppliers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preferred_regions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_topics: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("idx_user_preferences_user_id", "user_id"),)


class UserNewsFeed(BaseModel):
    """Materialized per-user news feed (what will be shown to users)."""

    __tablename__ = "user_news_feed"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_article_id: Mapped[int] = mapped_column(nullable=False)

    top_level_category: Mapped[str] = mapped_column(String(50), nullable=False)
    rank_score: Mapped[float] = mapped_column(nullable=False)
    match_reasons: Mapped[dict] = mapped_column(JSON, nullable=False)

    related_sourcing_event_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    surfaced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_user_feed_user_id", "user_id"),
        Index("idx_user_surfaced", "user_id", "surfaced_at"),
        Index("idx_rank_score", "rank_score"),
    )
