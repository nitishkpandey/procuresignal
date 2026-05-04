"""Article normalization pipeline."""

from typing import Optional

from procuresignal.normalization.language import LanguageValidator
from procuresignal.normalization.quality_filters import QualityGates
from procuresignal.normalization.source_trust import SourceTrustFilter
from procuresignal.retrieval import RawArticle


class ArticleNormalizer:
    """Normalize articles across all providers."""

    @staticmethod
    def normalize_text(text: Optional[str]) -> Optional[str]:
        """Normalize text fields.

        - Strip whitespace
        - Remove extra newlines
        - Decode HTML entities
        """
        if not text:
            return None

        # Strip whitespace
        text = text.strip()

        # Remove extra newlines
        import re

        text = re.sub(r"\n+", "\n", text)

        # Decode HTML entities (if needed)
        try:
            import html

            text = html.unescape(text)
        except Exception:
            pass

        return text if len(text) > 0 else None

    @staticmethod
    async def normalize(article: RawArticle) -> Optional[RawArticle]:
        """Normalize article completely.

        Args:
            article: Raw article from retrieval

        Returns:
            Normalized article or None if failed checks
        """
        # Check if source is blocked
        if SourceTrustFilter.is_blocked(article.article_url):
            return None

        # Quality checks
        passed, failures = await QualityGates.check_all(article)
        if not passed:
            return None

        # Normalize text fields
        normalized_title = ArticleNormalizer.normalize_text(article.title)
        if normalized_title is None:
            return None
        article.title = normalized_title
        article.description = ArticleNormalizer.normalize_text(article.description)
        article.content_snippet = ArticleNormalizer.normalize_text(article.content_snippet)

        # Validate language
        if article.description or article.content_snippet:
            is_valid, detected_lang = await LanguageValidator.validate(
                article.title,
                article.description,
                article.content_snippet,
                article.language,
            )

            if detected_lang:
                article.language = detected_lang

            if not is_valid:
                return None

        return article
