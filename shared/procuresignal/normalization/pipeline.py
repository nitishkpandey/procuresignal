"""Normalization pipeline orchestration."""

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.normalization.deduplicator import ArticleDeduplicator
from procuresignal.normalization.normalizer import ArticleNormalizer
from procuresignal.retrieval import RawArticle


class NormalizationPipeline:
    """Orchestrate the full normalization process."""

    @staticmethod
    async def process_articles(
        session: AsyncSession,
        articles: list[RawArticle],
    ) -> tuple[list[RawArticle], int, int, int]:
        """Process articles through normalization pipeline.

        Args:
            session: Database session
            articles: Raw articles from retrieval

        Returns:
            (normalized_articles, duplicates, quality_failures, errors)
        """
        normalized = []
        duplicates = 0
        quality_failures = 0
        errors = 0

        for article in articles:
            try:
                # Check for duplicates
                is_dup = await ArticleDeduplicator.is_duplicate(session, article)
                if is_dup:
                    duplicates += 1
                    continue

                # Normalize
                normalized_article = await ArticleNormalizer.normalize(article)
                if normalized_article is None:
                    quality_failures += 1
                    continue

                normalized.append(normalized_article)

            except Exception:
                errors += 1
                continue

        return normalized, duplicates, quality_failures, errors
