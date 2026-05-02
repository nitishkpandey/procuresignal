"""Article normalization (Phase 3 will expand this)."""

from typing import Optional

from procuresignal.retrieval.base import RawArticle


class ArticleNormalizer:
    """Normalize articles across all providers."""

    @staticmethod
    def normalize(article: RawArticle) -> Optional[RawArticle]:
        """Normalize article fields.

        For now, just ensure required fields are present.
        Phase 3 will add deduplication, language detection, etc.
        """
        # Ensure title is not empty
        if not article.title or len(article.title.strip()) == 0:
            return None

        # Ensure URL is present
        if not article.article_url or len(article.article_url.strip()) == 0:
            return None

        # Basic cleanup
        article.title = article.title.strip()

        return article
