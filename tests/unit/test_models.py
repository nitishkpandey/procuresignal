"""Tests for SQLAlchemy models."""

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.procuresignal.models import (
    Base,
    NewsArticleRaw,
    NewsArticleProcessed,
    UserNewsPreference,
    NewsPipelineRun,
)


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session


@pytest.mark.asyncio
async def test_create_raw_article(async_session: AsyncSession) -> None:
    """Test creating a raw article."""
    article = NewsArticleRaw(
        provider="newsapi",
        provider_article_id="test-123",
        query_group="supplier_risk",
        ingest_hash="test-hash-123",
        title="Test Article",
        article_url="https://example.com",
        source_name="Test Source",
        published_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
    )

    async_session.add(article)
    await async_session.commit()

    assert article.id is not None
    assert article.title == "Test Article"
    assert article.provider == "newsapi"


@pytest.mark.asyncio
async def test_create_processed_article(async_session: AsyncSession) -> None:
    """Test creating a processed article."""
    raw = NewsArticleRaw(
        provider="newsapi",
        query_group="test",
        ingest_hash="raw-hash",
        title="Raw Title",
        article_url="https://example.com",
        source_name="Source",
        published_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
    )
    async_session.add(raw)
    await async_session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title="Normalized Title",
        summary="This is a test summary.",
        top_level_category="suppliers",
        signal_score=0.85,
        processed_at=datetime.utcnow(),
    )
    async_session.add(processed)
    await async_session.commit()

    assert processed.id is not None
    assert processed.raw_article_id == raw.id
    assert processed.signal_score == 0.85


@pytest.mark.asyncio
async def test_create_user_preference(async_session: AsyncSession) -> None:
    """Test creating user preferences."""
    prefs = UserNewsPreference(
        user_id="test-user-123",
        preferred_suppliers=["Bosch", "Siemens"],
        preferred_regions=["Germany", "Poland"],
        preferred_categories=["automotive"],
        onboarding_completed=True,
    )

    async_session.add(prefs)
    await async_session.commit()

    assert prefs.user_id == "test-user-123"
    assert len(prefs.preferred_suppliers) == 2
    assert "Bosch" in prefs.preferred_suppliers


@pytest.mark.asyncio
async def test_pipeline_run_metrics(async_session: AsyncSession) -> None:
    """Test creating a pipeline run record."""
    run = NewsPipelineRun(
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        status="success",
        articles_fetched=100,
        articles_kept=45,
        articles_rejected=55,
    )

    async_session.add(run)
    await async_session.commit()

    assert run.status == "success"
    assert run.articles_fetched == 100
    assert run.articles_kept + run.articles_rejected == 100
