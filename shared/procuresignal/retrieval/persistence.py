"""Persistence layer for raw articles."""

import hashlib
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
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

                # Create model instance
                db_article = NewsArticleRaw(
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
                    published_at=article.published_at,
                    language=article.language,
                    raw_payload_json=article.raw_payload_json,
                    ingested_at=datetime.utcnow(),
                )

                # Use INSERT ... ON CONFLICT DO NOTHING for upsert
                stmt = (
                    insert(NewsArticleRaw)
                    .values(
                        provider=db_article.provider,
                        provider_article_id=db_article.provider_article_id,
                        query_group=db_article.query_group,
                        ingest_hash=db_article.ingest_hash,
                        title=db_article.title,
                        description=db_article.description,
                        content_snippet=db_article.content_snippet,
                        article_url=db_article.article_url,
                        canonical_url=db_article.canonical_url,
                        source_name=db_article.source_name,
                        source_url=db_article.source_url,
                        published_at=db_article.published_at,
                        language=db_article.language,
                        raw_payload_json=db_article.raw_payload_json,
                        ingested_at=db_article.ingested_at,
                    )
                    .on_conflict_do_nothing(index_elements=["ingest_hash"])
                )

                result = await session.execute(stmt)

                # Check if row was inserted
                if result.rowcount > 0:
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
