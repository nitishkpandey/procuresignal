"""Tests for risk event persistence."""

from datetime import datetime

import pytest
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw, RiskEvent
from procuresignal.risk_events.persistence import build_event_key, generate_risk_events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def risk_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_article(session: AsyncSession, suffix: str = "1") -> NewsArticleProcessed:
    raw = NewsArticleRaw(
        provider="rss",
        provider_article_id=f"risk-{suffix}",
        query_group="supplier_risk",
        ingest_hash=f"risk-hash-{suffix}",
        title="Attack threatens Qatar exports",
        description="Energy buyers are reviewing regional risk.",
        content_snippet="The attack raises concern for buyers.",
        article_url=f"https://example.com/risk-{suffix}",
        source_name="Reuters",
        published_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
    )
    session.add(raw)
    await session.flush()
    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=raw.title,
        summary="Energy buyers are reviewing regional risk after an attack.",
        top_level_category="energy",
        signal_tags=[],
        priority_signal=None,
        detected_regions=["Qatar"],
        detected_suppliers=[],
        detected_categories=["energy"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="openai/test",
        language="en",
        processed_at=datetime.utcnow(),
    )
    session.add(processed)
    await session.commit()
    return processed


def test_build_event_key_is_stable() -> None:
    first = build_event_key(1, "tariff", ["Bosch"], ["Germany", "Poland"])
    second = build_event_key(1, "tariff", ["bosch"], ["poland", "germany"])

    assert first == second


@pytest.mark.asyncio
async def test_generate_risk_events_is_idempotent(risk_session: AsyncSession) -> None:
    await _seed_article(risk_session)

    first = await generate_risk_events(risk_session, days_back=7, limit=50)
    second = await generate_risk_events(risk_session, days_back=7, limit=50)
    result = await risk_session.execute(select(RiskEvent))
    events = result.scalars().all()

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1
    assert len(events) == 1
    assert events[0].risk_type in {"geopolitical", "regional_conflict"}


@pytest.mark.asyncio
async def test_generate_risk_events_skips_article_failures(
    risk_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _seed_article(risk_session, "1")
    await _seed_article(risk_session, "2")

    from procuresignal.risk_events import persistence

    original_detector = persistence.detect_risk_events

    def detector_with_one_failure(processed, raw):
        if processed.id == first.id:
            raise RuntimeError("bad article")
        return original_detector(processed, raw)

    monkeypatch.setattr(persistence, "detect_risk_events", detector_with_one_failure)

    result = await generate_risk_events(risk_session, days_back=7, limit=50)

    assert result.scanned == 2
    assert result.created == 1
    assert result.errors == 1
    assert len((await risk_session.execute(select(RiskEvent))).scalars().all()) == 1
