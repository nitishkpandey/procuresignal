"""Tests for SQLAlchemy models."""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.procuresignal.models import (
    Base,
    NewsArticleProcessed,
    NewsArticleRaw,
    NewsPipelineRun,
    NewsRetrievalRun,
    NewsRetrievalSourceOutcome,
    RiskEvent,
    UserNewsPreference,
)
from shared.procuresignal.retrieval.base import RawArticle


def test_raw_article_provenance_defaults_preserve_existing_callers() -> None:
    article = RawArticle(
        provider="rss",
        provider_article_id="ecb-1",
        query_group="fx",
        title="ECB publishes monetary policy update",
        description="Official communication",
        content_snippet="Official communication",
        article_url="https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html",
        canonical_url="https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html",
        source_name="European Central Bank",
        source_url="https://www.ecb.europa.eu/",
        published_at=datetime(2026, 7, 13, 10, 0),
        language="en",
    )
    assert article.source_id is None
    assert article.source_domains == ()
    assert article.retrieved_at is None


@pytest.mark.asyncio
async def test_retrieval_outcome_is_unique_per_run_and_source(async_session) -> None:
    run = NewsRetrievalRun(
        run_key="scheduled:2026-07-13T12:00Z",
        status="running",
        registry_version="sources-v1",
        lease_owner="worker-a",
        lease_expires_at=datetime(2026, 7, 13, 13, 5),
        started_at=datetime(2026, 7, 13, 12, 0),
    )
    values = dict(
        source_id="ecb_press",
        status="success",
        attempted_count=1,
        fetched_count=1,
        accepted_count=1,
        inserted_count=1,
        duplicate_count=0,
        rejected_count=0,
        failed_count=0,
    )
    async_session.add_all(
        [
            NewsRetrievalSourceOutcome(run=run, **values),
            NewsRetrievalSourceOutcome(run=run, **values),
        ]
    )
    with pytest.raises(IntegrityError):
        await async_session.commit()


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
    assert processed.enrichment_method is None
    assert processed.enrichment_reason is None
    assert processed.enrichment_policy_version is None
    assert processed.content_fingerprint is None
    assert processed.deterministic_confidence is None
    assert processed.llm_used is False


@pytest.mark.asyncio
async def test_processed_article_raw_id_is_unique(async_session: AsyncSession) -> None:
    first = NewsArticleProcessed(
        raw_article_id=99,
        normalized_title="First",
        summary="First valid summary.",
        top_level_category="general",
        processed_at=datetime.utcnow(),
    )
    duplicate = NewsArticleProcessed(
        raw_article_id=99,
        normalized_title="Second",
        summary="Second valid summary.",
        top_level_category="general",
        processed_at=datetime.utcnow(),
    )
    async_session.add_all([first, duplicate])
    with pytest.raises(IntegrityError):
        await async_session.commit()


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


@pytest.mark.asyncio
async def test_create_risk_event(async_session: AsyncSession) -> None:
    """Test creating an idempotent risk event."""

    event = RiskEvent(
        event_key="article-1:tariff:germany",
        processed_article_id=1,
        risk_type="tariff",
        severity="medium",
        confidence=0.82,
        affected_suppliers=["Bosch"],
        affected_locations=["Germany"],
        affected_categories=["automotive"],
        evidence_snippet="New import duty raises landed cost exposure.",
        recommendation="Check landed cost and tariff exposure before confirming new purchase orders.",
        source_name="Reuters",
        source_url="https://example.com",
        published_at=datetime.utcnow(),
        status="new",
    )

    async_session.add(event)
    await async_session.commit()

    assert event.id is not None
    assert event.event_key == "article-1:tariff:germany"
    assert event.affected_suppliers == ["Bosch"]
