"""Feed response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ArticleInFeed(BaseModel):
    """Article in personalized feed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    category: str
    signal_tags: list[str] = Field(default_factory=list)
    priority_signal: Optional[str] = None
    source_name: str
    published_at: datetime
    article_url: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    rank: int = Field(..., ge=1)


class FeedResponse(BaseModel):
    """Personalized feed response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    articles: list[ArticleInFeed]
    total_count: int = Field(..., ge=0)
    generated_at: datetime
    days_included: int = Field(default=7, ge=1, le=30)
