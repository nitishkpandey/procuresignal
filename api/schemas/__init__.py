"""API schemas."""

from .article import ArticleDetail, ArticleReadResponse, SearchResponse, SearchResult
from .feed import ArticleInFeed, FeedResponse
from .preference import (
    PreferenceBulkResponse,
    PreferenceBulkUpdate,
    PreferenceResponse,
    PreferenceUpdate,
)

__all__ = [
    "ArticleDetail",
    "ArticleInFeed",
    "ArticleReadResponse",
    "FeedResponse",
    "PreferenceBulkResponse",
    "PreferenceBulkUpdate",
    "PreferenceResponse",
    "PreferenceUpdate",
    "SearchResponse",
    "SearchResult",
]
