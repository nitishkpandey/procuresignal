"""Deduplication logic for articles."""

import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleRaw
from procuresignal.retrieval import RawArticle


class ArticleDeduplicator:
    """Deduplicate articles across multiple sources and runs."""

    @staticmethod
    def create_url_hash(url: str) -> str:
        """Create hash from canonical URL.

        Removes tracking params, www prefix, and fragments.
        """
        if not url:
            return ""

        # Parse URL
        parsed = urlparse(url.lower())

        # Remove tracking parameters
        path = parsed.path
        domain = parsed.netloc.replace("www.", "")

        # Create canonical form
        canonical = f"{domain}{path}"

        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def create_title_hash(title: str) -> str:
        """Create hash from normalized title.

        Removes punctuation, extra spaces, normalizes case.
        """
        if not title:
            return ""

        # Lowercase
        normalized = title.lower()

        # Remove punctuation and extra spaces
        import re

        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def create_ingest_hash(title: str, source: str, published_at: datetime) -> str:
        """Create deterministic hash for final deduplication.

        Combines title + source + publication date.
        This is the primary dedup key.
        """
        if not title or not source:
            return ""

        combined = f"{title.strip()}|{source.strip()}|{published_at.isoformat()}"
        return hashlib.sha256(combined.encode()).hexdigest()

    @staticmethod
    async def is_duplicate(
        session: AsyncSession,
        article: RawArticle,
    ) -> bool:
        """Check if article is duplicate in database.

        Uses three-level deduplication:
        1. URL hash
        2. Title hash + source + date window
        3. Ingest hash
        """

        # Level 1: URL deduplication
        candidate_url: str | None = article.canonical_url or article.article_url
        url_hash = ""
        if candidate_url:
            url_hash = ArticleDeduplicator.create_url_hash(candidate_url)
        if url_hash:
            existing = await session.execute(
                select(NewsArticleRaw).where(NewsArticleRaw.ingest_hash == url_hash).limit(1)
            )
            if existing.scalar_one_or_none():
                return True

        # Level 2: Title hash + source + date window
        title_hash = ArticleDeduplicator.create_title_hash(article.title)
        if title_hash:
            date_window = article.published_at - timedelta(hours=48)
            existing = await session.execute(
                select(NewsArticleRaw)
                .where(
                    NewsArticleRaw.source_name == article.source_name,
                    NewsArticleRaw.published_at >= date_window,
                    NewsArticleRaw.published_at <= article.published_at,
                    NewsArticleRaw.ingest_hash == title_hash,
                )
                .limit(1)
            )
            if existing.scalar_one_or_none():
                return True

        # Level 3: Ingest hash
        ingest_hash = ArticleDeduplicator.create_ingest_hash(
            article.title,
            article.source_name,
            article.published_at,
        )
        if ingest_hash:
            existing = await session.execute(
                select(NewsArticleRaw).where(NewsArticleRaw.ingest_hash == ingest_hash).limit(1)
            )
            if existing.scalar_one_or_none():
                return True

        return False
