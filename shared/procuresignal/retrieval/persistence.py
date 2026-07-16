"""Persistence layer for raw articles."""

import hashlib
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleRaw
from procuresignal.retrieval.base import RawArticle


class ArticlePersistence:
    """Persist raw articles to database."""

    @staticmethod
    async def save_articles(
        session: AsyncSession,
        articles: list[RawArticle],
    ) -> tuple[int, int, int]:
        """Save articles to database with deduplication.

        Args:
            session: Async database session
            articles: List of RawArticle objects to save

        Returns:
            Tuple of (inserted, duplicates, errors)
        """
        inserted = 0
        duplicates = 0
        errors = 0

        for article in articles:
            try:
                # Create ingest hash for deduplication
                ingest_hash = ArticlePersistence._create_ingest_hash(
                    article.title,
                    article.source_name,
                    article.published_at,
                )

                # Use INSERT ... ON CONFLICT DO NOTHING for upsert
                insert = (
                    sqlite_insert
                    if session.bind is not None and session.bind.dialect.name == "sqlite"
                    else postgresql_insert
                )
                stmt = (
                    insert(NewsArticleRaw)
                    .values(
                        provider=article.provider,
                        provider_article_id=article.provider_article_id,
                        query_group=article.query_group,
                        ingest_hash=ingest_hash,
                        title=article.title,
                        description=article.description,
                        content_snippet=article.content_snippet,
                        article_url=article.article_url,
                        canonical_url=article.canonical_url,
                        source_name=article.source_name,
                        source_url=article.source_url,
                        source_id=article.source_id,
                        source_class=article.source_class,
                        source_domains=list(article.source_domains),
                        source_countries=list(article.source_countries),
                        registry_version=article.registry_version,
                        retrieved_at=article.retrieved_at,
                        source_published_at_raw=article.source_published_at_raw,
                        published_at=article.published_at,
                        language=article.language,
                        raw_payload_json=article.raw_payload_json,
                        ingested_at=datetime.utcnow(),
                    )
                    .on_conflict_do_nothing(index_elements=["ingest_hash"])
                )

                async with session.begin_nested():
                    result = await session.execute(stmt)

                # Check if row was inserted
                if getattr(result, "rowcount", 0) > 0:
                    inserted += 1
                else:
                    duplicates += 1

            except Exception:
                errors += 1
                continue

        # Commit all inserts
        await session.commit()

        return inserted, duplicates, errors

    @staticmethod
    def _create_ingest_hash(title: str, source: str, published_at: datetime) -> str:
        """Create deterministic hash for deduplication.

        Combines title + source + publication date for uniqueness.
        """
        combined = f"{title}|{source}|{published_at.isoformat()}"
        return hashlib.sha256(combined.encode()).hexdigest()
