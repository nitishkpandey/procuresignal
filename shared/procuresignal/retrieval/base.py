"""Base provider interface for news sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RawArticle:
    """Normalized article from any source."""

    provider: str  # "newsapi", "gdelt", "rss"
    provider_article_id: Optional[str]  # ID from source
    query_group: str  # "supplier_risk", "tariff", etc.

    title: str
    description: Optional[str]
    content_snippet: Optional[str]

    article_url: str
    canonical_url: Optional[str]
    source_name: str
    source_url: Optional[str]

    published_at: datetime
    language: str = "en"

    raw_payload_json: Optional[dict] = None


class NewsProvider(ABC):
    """Abstract base class for news providers."""

    def __init__(self, name: str):
        """Initialize provider.

        Args:
            name: Provider name (newsapi, gdelt, rss)
        """
        self.name = name

    @abstractmethod
    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        """Fetch articles for given query groups.

        Args:
            query_groups: List of query groups to fetch
                Example: ["supplier_risk", "tariff_changes", "logistics"]

        Returns:
            List of normalized RawArticle objects
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is accessible.

        Returns:
            True if provider is reachable and working
        """
        pass
