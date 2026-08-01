"""API schemas."""

from .article import ArticleDetail, ArticleReadResponse, SearchResponse, SearchResult
from .feed import ArticleInFeed, FeedResponse
from .preference import (
    PreferenceResponse,
    PreferenceUpdate,
)

__all__ = [
    "ArticleDetail",
    "ArticleInFeed",
    "ArticleReadResponse",
    "FeedResponse",
    "PreferenceResponse",
    "PreferenceUpdate",
    "SearchResponse",
    "SearchResult",
]
