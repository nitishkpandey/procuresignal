"""Integration tests for the cost-aware enrichment cascade."""

from datetime import datetime

import pytest
from procuresignal.enrichment import (
    DeterministicAnalysis,
    EnrichmentOutput,
    EnrichmentPipeline,
    EnrichmentPolicy,
)
from procuresignal.models import Base, EnrichmentCacheEntry, NewsArticleProcessed, NewsArticleRaw
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


class _FailingClient(_Client):
    async def call(self, *_args, **_kwargs) -> str:
        self.calls += 1
        raise RuntimeError("OpenAI unavailable")


class _ExplodingAnalysis:
    def analyze(self, *_args, **_kwargs):
        raise AssertionError("cache hit must not run deterministic analysis")


class _FailingCache:
    async def get(self, *_args, **_kwargs):
        return None

    async def put(self, *_args, **_kwargs):
        raise RuntimeError("database write failed")


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
    cached = await EnrichmentPipeline(
        client,
        deterministic_enricher=_ExplodingAnalysis(),
        policy=EnrichmentPolicy(min_deterministic_confidence=0.7),
    ).process_raw_articles(session, [second])

    assert client.calls == 0
    assert initial.metrics.deterministic == 1
    assert cached.metrics.cached == 1
    assert cached.saved == 1
    saved = await session.scalar(
        select(NewsArticleProcessed).where(NewsArticleProcessed.raw_article_id == second.id)
    )
    assert saved is not None
    assert saved.enrichment_method == "cached"
    assert saved.enrichment_reason == "compatible_cache_hit"
    assert saved.deterministic_confidence is None


@pytest.mark.asyncio
async def test_deterministic_route_never_invokes_lazy_client_factory(
    session: AsyncSession,
) -> None:
    raw = _raw("lazy-deterministic")
    session.add(raw)
    await session.commit()

    def forbidden_factory():
        raise AssertionError("deterministic route invoked the OpenAI factory")

    result = await EnrichmentPipeline(
        llm_client_factory=forbidden_factory,
        deterministic_enricher=_Analysis(0.9, 0.9),
    ).process_raw_articles(session, [raw])

    assert result.metrics.deterministic == 1


@pytest.mark.asyncio
async def test_cache_hit_never_invokes_lazy_client_factory(session: AsyncSession) -> None:
    original, duplicate = _raw("lazy-cache-original"), _raw("lazy-cache-duplicate")
    duplicate.title = original.title
    duplicate.description = original.description
    session.add_all([original, duplicate])
    await session.commit()
    await EnrichmentPipeline(deterministic_enricher=_Analysis(0.9, 0.9)).process_raw_articles(
        session, [original]
    )

    def forbidden_factory():
        raise AssertionError("cache route invoked the OpenAI factory")

    result = await EnrichmentPipeline(
        llm_client_factory=forbidden_factory,
        deterministic_enricher=_ExplodingAnalysis(),
    ).process_raw_articles(session, [duplicate])

    assert result.metrics.cached == 1


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
    await session.refresh(raw)
    assert raw.enrichment_status == "deferred"
    assert raw.enrichment_attempt_count == 1
    assert raw.enrichment_next_attempt_at is not None
    assert raw.enrichment_lease_owner is None
    assert (
        sum(
            getattr(result.metrics, route)
            for route in ("cached", "deterministic", "llm", "skipped", "deferred", "failed")
        )
        == 1
    )


@pytest.mark.asyncio
async def test_skipped_article_is_durably_terminal_and_not_reprocessed(
    session: AsyncSession,
) -> None:
    raw = _raw("irrelevant")
    session.add(raw)
    await session.commit()
    pipeline = EnrichmentPipeline(deterministic_enricher=_Analysis(0.1, 0.9))

    first = await pipeline.process_raw_articles(session, [raw])
    second = await pipeline.process_raw_articles(session, [raw])

    await session.refresh(raw)
    assert first.metrics.skipped == 1
    assert second.metrics.skipped == 0
    assert second.already_processed == 1
    assert raw.enrichment_status == "skipped"
    assert raw.enrichment_lease_owner is None


@pytest.mark.asyncio
async def test_llm_output_merges_explicit_deterministic_entities(session: AsyncSession) -> None:
    raw = _raw("llm-merge")
    session.add(raw)
    await session.commit()
    llm = EnrichmentOutput(
        summary="Validated LLM summary for the procurement disruption.",
        category="general",
        signal_tags=[],
    ).model_dump_json()

    result = await EnrichmentPipeline(
        _Client(llm), deterministic_enricher=_Analysis(0.9, 0.4)
    ).process_raw_articles(session, [raw])
    saved = await session.scalar(
        select(NewsArticleProcessed).where(NewsArticleProcessed.raw_article_id == raw.id)
    )

    assert result.metrics.llm == 1
    assert saved is not None
    assert saved.detected_suppliers == ["Bosch"]
    assert saved.detected_regions == ["Germany"]
    assert saved.detected_categories == ["general", "automotive"]


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected", [(0.6, "deterministic"), (0.49, "failed")])
async def test_llm_failure_uses_explicit_fallback_threshold(
    session: AsyncSession, confidence: float, expected: str
) -> None:
    raw = _raw(str(confidence))
    session.add(raw)
    await session.commit()
    policy = EnrichmentPolicy(min_deterministic_confidence=0.72, min_fallback_confidence=0.5)

    result = await EnrichmentPipeline(
        _FailingClient(), policy=policy, deterministic_enricher=_Analysis(0.9, confidence)
    ).process_raw_articles(session, [raw])

    assert getattr(result.metrics, expected) == 1
    assert result.metrics.llm_calls == 1
    assert result.saved == (1 if expected == "deterministic" else 0)
    await session.refresh(raw)
    assert raw.enrichment_status == (
        "completed" if expected == "deterministic" else "enrichment_retry"
    )
    assert raw.enrichment_lease_owner is None


@pytest.mark.asyncio
async def test_same_input_raw_id_is_processed_once(session: AsyncSession) -> None:
    raw = _raw()
    session.add(raw)
    await session.commit()

    result = await EnrichmentPipeline(
        deterministic_enricher=_Analysis(0.9, 0.9)
    ).process_raw_articles(session, [raw, raw])

    assert result.saved == 1 and result.already_processed == 1
    assert result.metrics.deterministic == 1


@pytest.mark.asyncio
async def test_optional_client_supports_local_routes_and_defers_llm(session: AsyncSession) -> None:
    local, ambiguous = _raw("local"), _raw("ambiguous")
    ambiguous.title = "An uncertain but procurement-relevant development"
    session.add_all([local, ambiguous])
    await session.commit()

    local_result = await EnrichmentPipeline(
        deterministic_enricher=_Analysis(0.9, 0.9)
    ).process_raw_articles(session, [local])
    deferred = await EnrichmentPipeline(
        deterministic_enricher=_Analysis(0.9, 0.4)
    ).process_raw_articles(session, [ambiguous])

    assert local_result.metrics.deterministic == 1
    assert deferred.metrics.deferred == 1 and deferred.saved == 0


@pytest.mark.asyncio
async def test_corrupt_cache_is_miss_and_continues_deterministically(session: AsyncSession) -> None:
    raw = _raw()
    session.add(raw)
    await session.commit()
    from procuresignal.enrichment.fingerprint import content_fingerprint
    from procuresignal.retrieval import RawArticle

    article = RawArticle(
        provider=raw.provider,
        provider_article_id=raw.provider_article_id,
        query_group=raw.query_group,
        title=raw.title,
        description=raw.description,
        content_snippet=raw.content_snippet,
        article_url=raw.article_url,
        canonical_url=raw.canonical_url,
        source_name=raw.source_name,
        source_url=raw.source_url,
        published_at=raw.published_at,
        language=raw.language,
        raw_payload_json=raw.raw_payload_json,
    )
    fingerprint = content_fingerprint(
        article, policy_version="cost-v1", taxonomy_version="signals-v1"
    )
    session.add(
        EnrichmentCacheEntry(
            content_fingerprint=fingerprint,
            policy_version="cost-v1",
            taxonomy_version="signals-v1",
            payload={"summary": "short"},
            original_method="llm",
        )
    )
    await session.commit()

    result = await EnrichmentPipeline(
        deterministic_enricher=_Analysis(0.9, 0.9)
    ).process_raw_articles(session, [raw])

    assert result.metrics.cache_misses == 1
    assert result.metrics.deterministic == 1


@pytest.mark.asyncio
async def test_database_error_rolls_back_entire_batch(session: AsyncSession) -> None:
    raw = _raw()
    session.add(raw)
    await session.commit()
    pipeline = EnrichmentPipeline(deterministic_enricher=_Analysis(0.9, 0.9), cache=_FailingCache())

    with pytest.raises(RuntimeError, match="database write failed"):
        await pipeline.process_raw_articles(session, [raw])

    assert await session.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 0
    assert session.is_active


@pytest.mark.asyncio
async def test_unique_violation_savepoint_keeps_session_usable(session: AsyncSession) -> None:
    def processed(title: str) -> NewsArticleProcessed:
        return NewsArticleProcessed(
            raw_article_id=777,
            normalized_title=title,
            summary="A sufficiently detailed processed article summary.",
            top_level_category="general",
            processed_at=datetime.utcnow(),
        )

    assert await EnrichmentPipeline._add_processed(session, processed("first")) is True
    await session.commit()
    assert await EnrichmentPipeline._add_processed(session, processed("duplicate")) is False

    assert session.is_active
    assert await session.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 1


@pytest.mark.asyncio
async def test_two_sessions_enforce_processed_raw_identity(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def processed(title: str) -> NewsArticleProcessed:
        return NewsArticleProcessed(
            raw_article_id=888,
            normalized_title=title,
            summary="A sufficiently detailed processed article summary.",
            top_level_category="general",
            processed_at=datetime.utcnow(),
        )

    async with maker() as first, maker() as second:
        assert await EnrichmentPipeline._add_processed(first, processed("first")) is True
        await first.commit()
        assert await EnrichmentPipeline._add_processed(second, processed("duplicate")) is False
        assert second.is_active
        assert await second.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 1
    await engine.dispose()
