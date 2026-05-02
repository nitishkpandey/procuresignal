"""Tests for news retrieval providers."""

from datetime import datetime

import pytest
from procuresignal.retrieval import (
    GDELTProvider,
    NewsAPIProvider,
    RawArticle,
    RSSProvider,
)


@pytest.mark.asyncio
async def test_raw_article_creation() -> None:
    """Test creating a RawArticle."""
    article = RawArticle(
        provider="newsapi",
        provider_article_id="123",
        query_group="supplier_risk",
        title="Bosch announces facility",
        description="Manufacturing expansion",
        content_snippet="New EV components...",
        article_url="https://example.com",
        canonical_url="https://example.com",
        source_name="Reuters",
        source_url="https://reuters.com",
        published_at=datetime.utcnow(),
        language="en",
    )

    assert article.provider == "newsapi"
    assert article.title == "Bosch announces facility"


@pytest.mark.asyncio
async def test_newsapi_provider_initialization() -> None:
    """Test NewsAPI provider initialization."""
    provider = NewsAPIProvider(api_key="test-key")

    assert provider.name == "newsapi"
    assert provider.api_key == "test-key"

    await provider.close()


@pytest.mark.asyncio
async def test_gdelt_provider_initialization() -> None:
    """Test GDELT provider initialization."""
    provider = GDELTProvider()

    assert provider.name == "gdelt"

    await provider.close()


@pytest.mark.asyncio
async def test_rss_provider_initialization() -> None:
    """Test RSS provider initialization."""
    provider = RSSProvider()

    assert provider.name == "rss"

    await provider.close()


@pytest.mark.asyncio
async def test_rss_provider_feeds_exist() -> None:
    """Test RSS provider has feeds configured."""
    provider = RSSProvider()

    assert len(provider.FEEDS) > 0
    assert "supplier_risk" in provider.FEEDS
    assert "regulatory" in provider.FEEDS

    await provider.close()


def test_ingest_hash_deterministic() -> None:
    """Test that ingest hash is deterministic."""
    from procuresignal.retrieval import ArticlePersistence

    title = "Test Article"
    source = "Reuters"
    date = datetime(2024, 4, 30, 10, 0, 0)

    hash1 = ArticlePersistence._create_ingest_hash(title, source, date)
    hash2 = ArticlePersistence._create_ingest_hash(title, source, date)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex
