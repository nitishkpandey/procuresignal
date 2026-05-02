"""RSS feed provider for regulatory and news sources."""

from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from procuresignal.retrieval.base import NewsProvider, RawArticle


class RSSProvider(NewsProvider):
    """RSS feed provider (unlimited free)."""

    # Curated list of high-quality RSS feeds for procurement
    FEEDS = {
        "supplier_risk": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.bloomberg.com/markets/news.rss",
        ],
        "regulatory": [
            "https://ec.europa.eu/growth/tools-databases/nando/exchange/rss",
            "https://www.ohchr.org/en/news-event-alerts/events/rss",
        ],
        "logistics": [
            "https://feeds.reuters.com/reuters/companyNews",
        ],
        "commodities": [
            "https://feeds.bloomberg.com/markets/commodities.rss",
        ],
    }

    def __init__(self) -> None:
        """Initialize RSS provider."""
        super().__init__("rss")
        self.client = httpx.AsyncClient(timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
    )
    async def _fetch_with_retry(self, url: str) -> str:
        """Fetch RSS feed with retry."""
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

    async def health_check(self) -> bool:
        """Check if RSS feeds are accessible."""
        try:
            # Try to fetch one major feed
            content = await self._fetch_with_retry("https://feeds.reuters.com/reuters/businessNews")
            return len(content) > 0
        except Exception:
            return False

    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        """Fetch articles from RSS feeds.

        Args:
            query_groups: List of query groups (used to select feeds)
                Example: ["supplier_risk", "regulatory"]

        Returns:
            List of RawArticle objects
        """
        articles = []

        # Select feeds based on query groups
        feeds_to_fetch = []
        for query_group in query_groups:
            if query_group in self.FEEDS:
                feeds_to_fetch.extend(self.FEEDS[query_group])

        # Fetch and parse each feed
        for feed_url in feeds_to_fetch:
            try:
                feed_content = await self._fetch_with_retry(feed_url)
                feed = feedparser.parse(feed_content)

                for entry in feed.entries[:20]:  # Limit per feed
                    article = RawArticle(
                        provider="rss",
                        provider_article_id=entry.get("id"),
                        query_group=query_groups[0],  # Default to first query group
                        title=entry.get("title", ""),
                        description=entry.get("summary"),
                        content_snippet=entry.get("summary"),
                        article_url=entry.get("link", ""),
                        canonical_url=entry.get("link"),
                        source_name=feed.feed.get("title", "Unknown"),
                        source_url=feed.feed.get("link"),
                        published_at=self._parse_datetime(entry),
                        language="en",
                        raw_payload_json=entry,
                    )
                    articles.append(article)

            except Exception:
                continue

        return articles

    @staticmethod
    def _parse_datetime(entry: dict) -> datetime:
        """Parse datetime from RSS entry."""
        # Try published_parsed first (struct_time)
        if "published_parsed" in entry and entry["published_parsed"]:
            try:
                from time import mktime

                return datetime.fromtimestamp(mktime(entry["published_parsed"]))
            except Exception:
                pass

        # Try published date string
        if "published" in entry:
            try:
                return parsedate_to_datetime(entry["published"])
            except Exception:
                pass

        # Fallback
        return datetime.utcnow()

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
