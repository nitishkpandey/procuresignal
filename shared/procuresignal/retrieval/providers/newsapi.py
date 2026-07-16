"""NewsAPI.org provider implementation."""

import json
import os
from dataclasses import replace
from datetime import datetime
from typing import Any, Optional

import httpx

from procuresignal.retrieval.base import NewsProvider, RawArticle, RetrievalFetchError
from procuresignal.retrieval.registry import SourceDefinition


class NewsAPIProvider(NewsProvider):
    """NewsAPI.org provider (100 requests/day free)."""

    BASE_URL = "https://newsapi.org/v2"
    EUROPE_BUSINESS_COUNTRIES = ("de", "fr", "gb", "it", "nl")
    COUNTRY_LANGUAGES = {
        "de": "de",
        "fr": "fr",
        "gb": "en",
        "it": "it",
        "nl": "nl",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        source: SourceDefinition | None = None,
        fetcher: Any = None,
    ):
        """Initialize NewsAPI provider.

        Args:
            api_key: NewsAPI.org API key (defaults to NEWSAPI_KEY env var)
        """
        if fetcher is None:
            super().__init__("newsapi")
        else:
            self.name = "newsapi"
        self.api_key = api_key or os.getenv("NEWSAPI_KEY", "")
        self.source = source
        self.fetcher = fetcher
        self.last_response_bytes = 0

    async def close(self) -> None:
        if self.fetcher is not None:
            await self.fetcher.aclose()
        else:
            await super().close()

    async def _json(self, url: str, params: dict) -> dict:
        if self.fetcher is None:
            return (await self._get(url, params)).json()
        assert self.source is not None
        result = await self.fetcher.fetch(replace(self.source, endpoint_url=url), params)
        self.last_response_bytes += result.response_bytes
        if not result.ok:
            raise RetrievalFetchError(replace(result, response_bytes=self.last_response_bytes))
        try:
            return json.loads(result.content or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid_json") from exc

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
                result = await self._json(
                    f"{self.BASE_URL}/everything",
                    {
                        "q": query,
                        "sortBy": "publishedAt",
                        "pageSize": 30,  # Max 100 per NewsAPI limits
                        "apiKey": self.api_key,
                    },
                )
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

            except RetrievalFetchError:
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit reached
                    return articles
                continue
            except Exception:
                continue

        articles.extend(await self._fetch_europe_business_headlines())
        return articles

    async def _fetch_europe_business_headlines(self) -> list[RawArticle]:
        """Fetch current business headlines from core European supplier markets."""
        page_size = int(os.getenv("NEWSAPI_EUROPE_PAGE_SIZE", "20"))
        articles: list[RawArticle] = []

        for country in self.EUROPE_BUSINESS_COUNTRIES:
            try:
                result = await self._json(
                    f"{self.BASE_URL}/top-headlines",
                    {
                        "country": country,
                        "category": "business",
                        "pageSize": page_size,
                        "apiKey": self.api_key,
                    },
                )
                if result.get("status") != "ok":
                    continue

                for item in result.get("articles", []):
                    url = item.get("url") or ""
                    article = RawArticle(
                        provider="newsapi",
                        provider_article_id=url or None,
                        query_group="europe_business",
                        title=item.get("title", ""),
                        description=item.get("description"),
                        content_snippet=item.get("content"),
                        article_url=url,
                        canonical_url=url or None,
                        source_name=item.get("source", {}).get("name", "Unknown"),
                        source_url=None,
                        published_at=self._parse_datetime(item.get("publishedAt")),
                        language=self.COUNTRY_LANGUAGES.get(country, "en"),
                        raw_payload_json={**item, "newsapi_country": country},
                    )
                    articles.append(article)
            except RetrievalFetchError:
                raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
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
