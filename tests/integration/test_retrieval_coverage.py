"""Offline, deterministic Phase 3 retrieval coverage gate."""

from pathlib import Path

from procuresignal.models import Base, NewsArticleRaw
from procuresignal.retrieval.base import FetchFailureCode, FetchResult
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.orchestrator import RetrievalOrchestrator, configured_registry
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.registry import ProcurementDomain
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

FIXTURES = Path("tests/fixtures/retrieval")
RECORDED_FEEDS = tuple(sorted(FIXTURES.glob("*.xml")))


def test_per_source_enable_overrides_are_explicit(monkeypatch):
    monkeypatch.setenv("SOURCE_EUROSTAT_UPDATES_ENABLED", "false")
    monkeypatch.setenv("SOURCE_EU_COUNCIL_PRESS_ENABLED", "true")

    configured = configured_registry()

    assert "eurostat_updates" not in {source.source_id for source in configured.enabled()}
    assert "eu_council_press" in {source.source_id for source in configured.enabled()}


async def test_production_registry_offline_coverage_and_idempotency(tmp_path, monkeypatch):
    """Exercise every enabled production source without network or LLM access."""

    def forbidden_llm(*_args, **_kwargs):
        raise AssertionError("retrieval coverage attempted to construct an OpenAI client")

    import procuresignal.chat.chat_client as chat_module
    import procuresignal.enrichment as enrichment_module
    import procuresignal.enrichment.enricher as enricher_module
    import procuresignal.enrichment.openai_client as client_module
    import procuresignal.enrichment.pipeline as pipeline_module

    import api.translation as translation_module
    import worker.tasks as worker_tasks_module

    monkeypatch.setattr(chat_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(enrichment_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(enricher_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(client_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(pipeline_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(translation_module, "OpenAILLMClient", forbidden_llm)
    monkeypatch.setattr(worker_tasks_module, "OpenAILLMClient", forbidden_llm)

    enabled = SOURCE_REGISTRY.enabled()
    assert RECORDED_FEEDS
    fixture_by_source = {
        definition.source_id: RECORDED_FEEDS[index % len(RECORDED_FEEDS)]
        for index, definition in enumerate(enabled)
    }
    exercised_fixtures: set[Path] = set()
    failing_source_id = enabled[-1].source_id

    class FixtureFetcher:
        def __init__(self, source_id: str) -> None:
            self.source_id = source_id

        async def fetch(self, definition):
            if self.source_id == failing_source_id:
                return FetchResult(failure_code=FetchFailureCode.HTTP_STATUS)
            fixture = fixture_by_source[definition.source_id]
            exercised_fixtures.add(fixture)
            content = fixture.read_bytes()
            return FetchResult(
                content=content,
                content_type="application/xml",
                final_url=definition.endpoint_url,
                response_bytes=len(content),
            )

    class RecordedProvider(RSSProvider):
        async def fetch_articles(self, query_groups):
            articles = await super().fetch_articles(query_groups)
            if self.source.source_id == enabled[0].source_id and articles:
                return [*articles, articles[0]]
            return articles

    def provider_factory(definition):
        return RecordedProvider(
            definition,
            FixtureFetcher(definition.source_id),
            registry_version=REGISTRY_VERSION,
        )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'coverage.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        orchestrator = RetrievalOrchestrator(
            session_factory=maker,
            registry=SOURCE_REGISTRY,
            registry_version=REGISTRY_VERSION,
            provider_factory=provider_factory,
        )
        result = await orchestrator.run("phase-3:recorded-fixtures")
        rerun = await RetrievalOrchestrator(
            session_factory=maker,
            registry=SOURCE_REGISTRY,
            registry_version=REGISTRY_VERSION,
            provider_factory=provider_factory,
        ).run("phase-3:recorded-fixtures")
        async with maker() as session:
            persisted_rows = list((await session.scalars(select(NewsArticleRaw))).all())
    finally:
        await engine.dispose()

    coverage = SOURCE_REGISTRY.validate_coverage()
    assert coverage.missing_domains == ()
    assert coverage.missing_authoritative_domains == ()
    # Approved security exception: the official sanctions object needs secret query
    # injection and is ~24.7 MiB, beyond SafeFetcher's reviewed 5 MiB ceiling.
    assert coverage.missing_structured_authoritative_domains == (ProcurementDomain.SANCTIONS,)
    assert result.llm_calls == 0
    assert result.sources_succeeded >= 1
    assert result.sources_failed >= 1
    assert (
        result.articles_fetched,
        result.articles_inserted,
        result.within_run_duplicates,
        result.database_duplicates,
    ) == (
        9,
        8,
        1,
        0,
    )
    assert rerun.articles_inserted == 0
    assert all(row.source_id and row.registry_version for row in persisted_rows)
    assert exercised_fixtures == set(RECORDED_FEEDS)
