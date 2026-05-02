"""GDELT Project provider (unlimited, free)."""

from datetime import datetime
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from procuresignal.retrieval.base import NewsProvider, RawArticle


class GDELTProvider(NewsProvider):
    """GDELT Project provider (unlimited free access)."""

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self) -> None:
        """Initialize GDELT provider."""
        super().__init__("gdelt")
        self.client = httpx.AsyncClient(timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, TimeoutError)),
    )
    async def _fetch_with_retry(self, url: str, params: dict) -> str:
        """Fetch from GDELT with retry."""
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.text

    async def health_check(self) -> bool:
        """Check if GDELT is accessible."""
        try:
            # GDELT doesn't require API key, always available
            await self._fetch_with_retry(
                self.BASE_URL,
                {
                    "query": "Brexit",
                    "mode": "json",
                    "maxrecords": 1,
                    "sort": "date_desc",
                },
            )
            return True
        except Exception:
            return False

    async def fetch_articles(self, query_groups: list[str]) -> list[RawArticle]:
        """Fetch articles from GDELT.

        Args:
            query_groups: List of query strings
                Example: ["Bosch manufacturing", "automotive tariff"]

        Returns:
            List of RawArticle objects
        """
        articles = []

        # GDELT searches best with specific terms
        gdelt_queries = {
            "supplier_risk": ["bankruptcy", "insolvency", "facility closure"],
            "logistics_disruption": ["port strike", "logistics disruption", "supply chain"],
            "tariff_changes": ["tariff", "trade restriction", "export ban"],
            "commodity_prices": ["steel price", "copper price", "raw material"],
            "regulatory": ["CBAM", "REACH regulation", "supply chain rules"],
            "regional": ["manufacturing", "facility"],
        }

        for query_group in query_groups:
            # Map query group to GDELT search terms
            search_terms = gdelt_queries.get(query_group, [query_group])

            for term in search_terms:
                try:
                    result_text = await self._fetch_with_retry(
                        self.BASE_URL,
                        {
                            "query": term,
                            "mode": "json",
                            "maxrecords": 50,
                            "sort": "date_desc",
                            "timespan": "7d",  # Last 7 days
                        },
                    )

                    # GDELT returns JSON with articles array
                    import json

                    result = json.loads(result_text)

                    for item in result.get("articles", []):
                        article = RawArticle(
                            provider="gdelt",
                            provider_article_id=item.get("id"),
                            query_group=query_group,
                            title=item.get("title", ""),
                            description=item.get("body"),
                            content_snippet=item.get("snippet"),
                            article_url=item.get("url", ""),
                            canonical_url=item.get("url"),
                            source_name=item.get("sourcecountry", "Unknown"),
                            source_url=None,
                            published_at=self._parse_datetime(item.get("sedate")),
                            language=item.get("language", "en"),
                            raw_payload_json=item,
                        )
                        articles.append(article)

                except Exception:
                    continue

        return articles

    @staticmethod
    def _parse_datetime(date_str: Optional[str]) -> datetime:
        """Parse GDELT datetime format (YYYYMMDDHHMMSS)."""
        if not date_str or len(date_str) < 8:
            return datetime.utcnow()

        try:
            # GDELT format: "20240430103000"
            return datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
        except Exception:
            return datetime.utcnow()

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
