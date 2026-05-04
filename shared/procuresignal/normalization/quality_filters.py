"""Quality filtering for articles."""

from dataclasses import dataclass
from typing import Optional

from procuresignal.retrieval import RawArticle


@dataclass
class QualityCheckResult:
    """Result of quality check."""

    passed: bool
    reason: Optional[str] = None
    severity: str = "warning"  # warning, error, critical


class QualityGates:
    """Quality filters for article content."""

    # Minimum content lengths
    MIN_TITLE_LENGTH = 10
    MAX_TITLE_LENGTH = 500
    MIN_DESCRIPTION_LENGTH = 20
    MIN_SNIPPET_LENGTH = 30

    # Spam indicators
    SPAM_KEYWORDS = {
        "click here",
        "buy now",
        "limited offer",
        "subscribe",
        "watch video",
        "ad",
    }

    @staticmethod
    def check_title(title: Optional[str]) -> QualityCheckResult:
        """Validate title."""
        if not title:
            return QualityCheckResult(False, "Missing title", "critical")

        title = title.strip()

        if len(title) < QualityGates.MIN_TITLE_LENGTH:
            return QualityCheckResult(False, "Title too short", "error")

        if len(title) > QualityGates.MAX_TITLE_LENGTH:
            return QualityCheckResult(False, "Title too long", "error")

        # Check for spam indicators
        title_lower = title.lower()
        for spam_word in QualityGates.SPAM_KEYWORDS:
            if spam_word in title_lower:
                return QualityCheckResult(False, f"Spam word detected: {spam_word}", "warning")

        return QualityCheckResult(True)

    @staticmethod
    def check_content(
        description: Optional[str],
        content_snippet: Optional[str],
    ) -> QualityCheckResult:
        """Validate article content."""

        # Need at least one content field
        if not description and not content_snippet:
            return QualityCheckResult(False, "No description or content", "error")

        # Check minimum lengths
        if description and len(description.strip()) >= QualityGates.MIN_DESCRIPTION_LENGTH:
            return QualityCheckResult(True)

        if content_snippet and len(content_snippet.strip()) >= QualityGates.MIN_SNIPPET_LENGTH:
            return QualityCheckResult(True)

        return QualityCheckResult(False, "Content too short or weak", "warning")

    @staticmethod
    def check_url(url: Optional[str]) -> QualityCheckResult:
        """Validate article URL."""
        if not url or len(url.strip()) == 0:
            return QualityCheckResult(False, "Missing URL", "critical")

        url = url.strip()

        # Must be valid HTTP(S)
        if not url.lower().startswith(("http://", "https://")):
            return QualityCheckResult(False, "Invalid URL scheme", "error")

        # URL shouldn't be too long (likely malformed)
        if len(url) > 2000:
            return QualityCheckResult(False, "URL too long", "error")

        return QualityCheckResult(True)

    @staticmethod
    def check_timestamp(article: RawArticle) -> QualityCheckResult:
        """Validate publication timestamp."""
        from datetime import datetime, timedelta

        if not article.published_at:
            return QualityCheckResult(False, "Missing publication date", "error")

        now = datetime.utcnow()

        # Don't accept future articles
        if article.published_at > now:
            return QualityCheckResult(False, "Article from future", "warning")

        # Don't accept very old articles (>2 years)
        two_years_ago = now - timedelta(days=730)
        if article.published_at < two_years_ago:
            return QualityCheckResult(False, "Article too old", "warning")

        return QualityCheckResult(True)

    @staticmethod
    async def check_all(article: RawArticle) -> tuple[bool, list[str]]:
        """Run all quality checks.

        Returns:
            (passed, reasons_if_failed)
        """
        failures: list[str] = []

        # Title check (critical)
        title_result = QualityGates.check_title(article.title)
        if not title_result.passed:
            if title_result.severity in ("critical", "error") and title_result.reason:
                failures.append(title_result.reason)

        # Content check
        content_result = QualityGates.check_content(
            article.description,
            article.content_snippet,
        )
        if (
            not content_result.passed
            and content_result.severity == "error"
            and content_result.reason
        ):
            failures.append(content_result.reason)

        # URL check (critical)
        url_result = QualityGates.check_url(article.article_url)
        if not url_result.passed:
            if url_result.severity in ("critical", "error") and url_result.reason:
                failures.append(url_result.reason)

        # Timestamp check
        timestamp_result = QualityGates.check_timestamp(article)
        if (
            not timestamp_result.passed
            and timestamp_result.severity == "error"
            and timestamp_result.reason
        ):
            failures.append(timestamp_result.reason)

        return len(failures) == 0, failures
