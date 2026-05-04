"""Tests for normalization and quality gates."""

from datetime import datetime

import pytest
from procuresignal.normalization import (
    ArticleDeduplicator,
    ArticleNormalizer,
    LanguageDetector,
    QualityGates,
    SourceTrustFilter,
)
from procuresignal.retrieval import RawArticle


def test_url_hash_deterministic() -> None:
    """Test URL hash is deterministic."""
    url = "https://www.reuters.com/article/test-123"

    hash1 = ArticleDeduplicator.create_url_hash(url)
    hash2 = ArticleDeduplicator.create_url_hash(url)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256


def test_title_hash_normalizes() -> None:
    """Test title hash normalizes variations."""
    # Different punctuation, same content
    title1 = "Bosch announces new facility!"
    title2 = "Bosch announces new facility"

    hash1 = ArticleDeduplicator.create_title_hash(title1)
    hash2 = ArticleDeduplicator.create_title_hash(title2)

    assert hash1 == hash2


def test_quality_title_too_short() -> None:
    """Test quality gate rejects short titles."""
    result = QualityGates.check_title("Hi")

    assert result.passed is False
    assert result.reason is not None and "too short" in result.reason.lower()


def test_quality_title_valid() -> None:
    """Test quality gate accepts valid title."""
    result = QualityGates.check_title("Bosch announces new manufacturing facility in Poland")

    assert result.passed is True


def test_quality_content_missing() -> None:
    """Test quality gate rejects missing content."""
    result = QualityGates.check_content(None, None)

    assert result.passed is False


def test_quality_content_valid() -> None:
    """Test quality gate accepts valid content."""
    description = "Bosch Group announced today that it will open a new manufacturing facility in Poznań, Poland."
    result = QualityGates.check_content(description, None)

    assert result.passed is True


def test_quality_url_invalid() -> None:
    """Test quality gate rejects invalid URLs."""
    result = QualityGates.check_url("not-a-url")

    assert result.passed is False


def test_quality_url_valid() -> None:
    """Test quality gate accepts valid URLs."""
    result = QualityGates.check_url("https://example.com/article")

    assert result.passed is True


def test_source_trust_blocked() -> None:
    """Test blocked source detection."""
    url = "https://example-spam.com/article"

    assert SourceTrustFilter.is_blocked(url) is True


def test_source_trust_score() -> None:
    """Test trust score retrieval."""
    url = "https://reuters.com/article"
    score = SourceTrustFilter.get_trust_score(url)

    assert score == 0.95  # Reuters is trusted


def test_language_supported() -> None:
    """Test language support check."""
    assert LanguageDetector.is_supported_language("en") is True
    assert LanguageDetector.is_supported_language("xx") is False


@pytest.mark.asyncio
async def test_article_normalizer() -> None:
    """Test article normalization."""
    article = RawArticle(
        provider="newsapi",
        provider_article_id="123",
        query_group="supplier_risk",
        title="Bosch announces new facility in Poland",
        description="Bosch Group opens new automotive facility",
        content_snippet="The facility will produce EV components",
        article_url="https://reuters.com/article",
        canonical_url="https://reuters.com/article",
        source_name="Reuters",
        source_url="https://reuters.com",
        published_at=datetime.utcnow(),
        language="en",
    )

    normalized = await ArticleNormalizer.normalize(article)

    assert normalized is not None
    assert normalized.title == "Bosch announces new facility in Poland"
