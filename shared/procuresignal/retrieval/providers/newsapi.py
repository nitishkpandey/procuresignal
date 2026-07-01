"""NewsAPI.org provider implementation."""

import os
from datetime import datetime
from typing import Optional

import httpx

from procuresignal.retrieval.base import NewsProvider, RawArticle


class NewsAPIProvider(NewsProvider):
    """NewsAPI.org provider (100 requests/day free)."""

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize NewsAPI provider.

        Args:
            api_key: NewsAPI.org API key (defaults to NEWSAPI_KEY env var)
        """
        super().__init__("newsapi")
        self.api_key = api_key or os.getenv("NEWSAPI_KEY", "")

    async def health_check(self) -> bool:
        """Check if NewsAPI is accessible."""
        if not self.api_key:
            return False

        try:
            response = await self._get(
                f"{self.BASE_URL}/top-headlines",
                {"country": "us", "pageSize": 1, "apiKey": self.api_key},
            )
            return response.json().get("status") == "ok"
        except Exception:
            return False

    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        """Fetch articles from NewsAPI for given queries.

        Args:
            query_groups: List of query strings
                Example: ["Bosch bankruptcy", "EV tariff", "supply chain"]

        Returns:
            List of RawArticle objects
        """
        if not self.api_key:
            return []

        articles = []

        for query in query_groups:
            try:
                response = await self._get(
                    f"{self.BASE_URL}/everything",
                    {
                        "q": query,
                        "sortBy": "publishedAt",
                        "pageSize": 30,  # Max 100 per NewsAPI limits
                        "apiKey": self.api_key,
                    },
                )
                result = response.json()

                if result.get("status") != "ok":
                    continue

                for item in result.get("articles", []):
                    article = RawArticle(
                        provider="newsapi",
                        provider_article_id=None,  # NewsAPI doesn't provide stable IDs
                        query_group=query,
                        title=item.get("title", ""),
                        description=item.get("description"),
                        content_snippet=item.get("content"),
                        article_url=item.get("url", ""),
                        canonical_url=item.get("url"),
                        source_name=item.get("source", {}).get("name", "Unknown"),
                        source_url=None,
                        published_at=self._parse_datetime(item.get("publishedAt")),
                        language="en",  # NewsAPI is primarily English
                        raw_payload_json=item,
                    )
                    articles.append(article)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit reached
                    break
                continue
            except Exception:
                continue

        return articles

    @staticmethod
    def _parse_datetime(date_str: Optional[str]) -> datetime:
        """Parse ISO 8601 datetime string."""
        if not date_str:
            return datetime.utcnow()
        try:
            # ISO format: "2024-04-30T10:30:00Z". Strip tzinfo — the DB column is
            # TIMESTAMP WITHOUT TIME ZONE and asyncpg rejects tz-aware values.
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return datetime.utcnow()
