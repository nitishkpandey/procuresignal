"""Integration tests for the cost-aware enrichment cascade."""

from datetime import datetime

import pytest
from procuresignal.enrichment import (
    DeterministicAnalysis,
    EnrichmentOutput,
    EnrichmentPipeline,
    EnrichmentPolicy,
)
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as value:
        yield value
    await engine.dispose()


def _raw(key: str = "1") -> NewsArticleRaw:
    now = datetime.utcnow()
    return NewsArticleRaw(
        provider="test",
        provider_article_id=key,
        query_group="supply_chain",
        ingest_hash=key,
        title="Bosch tariff disruption in Germany",
        description="Bosch faces a tariff-related supply disruption in Germany.",
        article_url=f"https://example.com/{key}",
        source_name="Example",
        published_at=now,
        ingested_at=now,
        language="en",
    )


class _Analysis:
    def __init__(self, relevance: float, confidence: float) -> None:
        self.result = DeterministicAnalysis(
            EnrichmentOutput(
                summary="Bosch faces a tariff-related supply disruption in Germany.",
                category="automotive",
                signal_tags=["tariff"],
                detected_suppliers=["Bosch"],
                detected_regions=["Germany"],
                detected_categories=["automotive"],
            ),
            relevance,
            confidence,
        )

    def analyze(self, *_args, **_kwargs) -> DeterministicAnalysis:
        return self.result


class _Client:
    model = "spy"

    def __init__(self, response: str = "") -> None:
        self.calls = 0
        self.total_tokens_used = 0
        self.response = response

    async def call(self, *_args, **_kwargs) -> str:
        self.calls += 1
        self.total_tokens_used += 17
        return self.response

    def get_usage_stats(self) -> dict:
        return {"total_tokens": self.total_tokens_used, "total_calls": self.calls}


@pytest.mark.asyncio
async def test_deterministic_and_cache_routes_make_zero_llm_calls(session: AsyncSession) -> None:
    first, second = _raw("one"), _raw("two")
    second.title, second.description = first.title, first.description
    session.add_all([first, second])
    await session.commit()
    client = _Client()
    pipeline = EnrichmentPipeline(
        client,
        deterministic_enricher=_Analysis(0.9, 0.9),
        policy=EnrichmentPolicy(min_deterministic_confidence=0.7),
    )

    initial = await pipeline.process_raw_articles(session, [first])
    cached = await pipeline.process_raw_articles(session, [second])

    assert client.calls == 0
    assert initial.metrics.deterministic == 1
    assert cached.metrics.cached == 1
    assert cached.saved == 1


@pytest.mark.asyncio
async def test_ambiguous_article_calls_llm_once_and_is_idempotent(session: AsyncSession) -> None:
    raw = _raw()
    session.add(raw)
    await session.commit()
    response = EnrichmentOutput(
        summary="Validated LLM summary for the procurement disruption.",
        category="automotive",
        signal_tags=["tariff"],
    ).model_dump_json()
    client = _Client(response)
    pipeline = EnrichmentPipeline(client, deterministic_enricher=_Analysis(0.9, 0.4))

    first = await pipeline.process_raw_articles(session, [raw])
    second = await pipeline.process_raw_articles(session, [raw])

    assert client.calls == 1
    assert first.metrics.llm == 1 and first.metrics.llm_calls == 1
    assert second.already_processed == 1 and second.metrics.skipped == 0
    assert await session.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_defers_without_persisting(session: AsyncSession) -> None:
    raw = _raw()
    session.add(raw)
    await session.commit()
    policy = EnrichmentPolicy(max_llm_tokens=1)
    result = await EnrichmentPipeline(
        _Client(), policy=policy, deterministic_enricher=_Analysis(0.9, 0.4)
    ).process_raw_articles(session, [raw])

    assert result.saved == 0 and result.metrics.deferred == 1
    assert await session.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 0
    assert (
        sum(
            getattr(result.metrics, route)
            for route in ("cached", "deterministic", "llm", "skipped", "deferred", "failed")
        )
        == 1
    )
