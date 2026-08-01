"""Offline, deterministic Phase 3 retrieval coverage gate."""

import ipaddress
from pathlib import Path

import httpx
from procuresignal.models import Base, NewsArticleRaw
from procuresignal.retrieval.base import FetchFailureCode, FetchResult
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.orchestrator import RetrievalOrchestrator, configured_registry
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.providers.sanctions import EUSanctionsProvider
from procuresignal.retrieval.registry import AdapterType
from procuresignal.retrieval.security import URLSafetyPolicy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

FIXTURES = Path("tests/fixtures/retrieval")
RSS_FIXTURES = tuple(
    FIXTURES / name
    for name in (
        "ecb_press.xml",
        "eu_commission_press.xml",
        "europe_commodities.xml",
        "europe_logistics.xml",
    )
)
SANCTIONS_FIXTURE = FIXTURES / "eu_financial_sanctions.xml"
RECORDED_FEEDS = (*RSS_FIXTURES, SANCTIONS_FIXTURE)


class MemoryCircuit:
    async def allow_circuit_request(self, _source_id, _owner, _now):
        return True

    async def record_circuit_failure(self, _source_id, _now):
        return None

    async def record_circuit_success(self, _source_id, _owner):
        return True


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def handle_async_request(self, _request):
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=self.content,
        )


async def public_resolver(_host, _port):
    return (ipaddress.ip_address("93.184.216.34"),)


def test_per_source_enable_overrides_are_explicit(monkeypatch):
    monkeypatch.setenv("SOURCE_EUROSTAT_UPDATES_ENABLED", "false")
    monkeypatch.setenv("SOURCE_EU_COUNCIL_PRESS_ENABLED", "true")

    configured = configured_registry()

    assert "eurostat_updates" not in {source.source_id for source in configured.enabled()}
    assert "eu_council_press" in {source.source_id for source in configured.enabled()}


async def test_production_registry_offline_coverage_and_idempotency(tmp_path, monkeypatch):
    """Exercise every enabled production source without network or LLM access."""
    monkeypatch.setenv("EU_FISMA_SANCTIONS_TOKEN", "offline-fixture-token")

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
    rss_enabled = [definition for definition in enabled if definition.adapter is AdapterType.RSS]
    fixture_by_source = {
        definition.source_id: RSS_FIXTURES[index % len(RSS_FIXTURES)]
        for index, definition in enumerate(rss_enabled)
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
        if definition.adapter is AdapterType.STRUCTURED_SANCTIONS:
            exercised_fixtures.add(SANCTIONS_FIXTURE)
            fetcher = SafeFetcher(
                policy=URLSafetyPolicy(resolver=public_resolver),
                circuit_store=MemoryCircuit(),
                owner="offline-coverage",
            )
            fetcher._client._transport = FixtureTransport(SANCTIONS_FIXTURE.read_bytes())
            return EUSanctionsProvider(definition, fetcher)
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
    # The reviewed sealed streaming adapter closes the structured sanctions gap
    # without changing SafeFetcher's ordinary five MiB ceiling.
    assert coverage.missing_structured_authoritative_domains == ()
    assert result.llm_calls == 0
    assert result.sources_succeeded >= 1
    assert result.sources_failed >= 1
    assert result.articles_fetched == 12
    assert result.articles_inserted == 11
    assert result.within_run_duplicates == 1
    assert result.database_duplicates == 0
    assert rerun.articles_inserted == 0
    assert all(row.source_id and row.registry_version for row in persisted_rows)
    assert exercised_fixtures == set(RECORDED_FEEDS)
    assert {
        row.provider_article_id for row in persisted_rows if row.provider == "eu_sanctions"
    } == {
        "eu-sanctions:EU.001:2024-01-02",
        "eu-sanctions:EU.001:2025-02-04",
        "eu-sanctions:EU.002:2023-06-01",
    }
