"""Article response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ArticleDetail(BaseModel):
    """Detailed article information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    description: Optional[str] = None
    content_snippet: Optional[str] = None
    category: str
    signal_tags: list[str] = Field(default_factory=list)
    priority_signal: Optional[str] = None
    detected_suppliers: list[str] = Field(default_factory=list)
    detected_regions: list[str] = Field(default_factory=list)
    detected_categories: list[str] = Field(default_factory=list)
    source_name: str
    source_url: str
    article_url: str
    published_at: datetime
    processed_at: datetime
    language: str
    llm_model: str


class SearchResult(BaseModel):
    """Search result item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    category: str
    published_at: datetime
    relevance: float = Field(..., ge=0.0, le=1.0)


class SearchResponse(BaseModel):
    """Search response."""

    model_config = ConfigDict(from_attributes=True)

    query: str
    total_results: int = Field(..., ge=0)
    results: list[SearchResult]
    search_time_ms: float = Field(..., ge=0.0)


class ArticleReadResponse(BaseModel):
    """Response for marking an article as read."""

    model_config = ConfigDict(from_attributes=True)

    article_id: int
    user_id: str
    read: bool
