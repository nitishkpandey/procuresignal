"""Base provider interface for news sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


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
        self.client = httpx.AsyncClient(timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
    )
    async def _get(self, url: str, params: Optional[dict] = None) -> httpx.Response:
        """Fetch a URL with exponential-backoff retry."""
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

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
