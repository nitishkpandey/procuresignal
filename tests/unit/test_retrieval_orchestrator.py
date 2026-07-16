import asyncio
from datetime import datetime, timedelta

import pytest
from procuresignal.models import Base, NewsArticleRaw, NewsRetrievalRun
from procuresignal.retrieval.base import FetchFailureCode, FetchResult, RawArticle
from procuresignal.retrieval.orchestrator import RetrievalOrchestrator, configured_registry
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.registry import (
    AdapterType,
    ProcurementDomain,
    SourceClass,
    SourceDefinition,
    SourceRegistry,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def source(source_id: str, host: str = "same.test") -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=source_id,
        homepage_url=f"https://{host}/",
        endpoint_url=f"https://{host}/feed",
        adapter=AdapterType.RSS,
        source_class=SourceClass.OFFICIAL,
        domains=frozenset({ProcurementDomain.REGULATION}),
        countries=("de",),
        languages=("en",),
        poll_minutes=60,
        item_limit=50,
        expected_content_types=("application/rss+xml",),
        allowed_hosts=(host,),
        trust_seed=0.9,
        license_note="test",
    )


@pytest.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'orchestrator.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def article(definition: SourceDefinition, suffix: str) -> RawArticle:
    return RawArticle(
        provider="rss",
        provider_article_id=suffix,
        query_group="regulation",
        title=f"Title {suffix}",
        description=None,
        content_snippet=None,
        article_url=f"https://articles.test/{suffix}",
        canonical_url=f"https://articles.test/{suffix}",
        source_name=definition.display_name,
        source_url=definition.homepage_url,
        published_at=datetime(2026, 7, 16),
        source_id=definition.source_id,
        source_class=definition.source_class.value,
        source_domains=("regulation",),
        source_countries=("de",),
        registry_version="test-v1",
        retrieved_at=datetime(2026, 7, 16, 12),
    )


async def test_bounded_concurrency_partial_failure_and_clients_close(maker):
    definitions = tuple(source(f"s{i}", "same.test" if i < 4 else f"h{i}.test") for i in range(8))
    active = total_peak = host_active = host_peak = 0
    closed: dict[str, int] = {}
    lock = asyncio.Lock()

    class Provider:
        def __init__(self, definition):
            self.definition = definition

        async def fetch_articles(self, _groups):
            nonlocal active, total_peak, host_active, host_peak
            async with lock:
                active += 1
                total_peak = max(total_peak, active)
                if self.definition.allowed_hosts[0] == "same.test":
                    host_active += 1
                    host_peak = max(host_peak, host_active)
            await asyncio.sleep(0.02)
            async with lock:
                active -= 1
                if self.definition.allowed_hosts[0] == "same.test":
                    host_active -= 1
            if self.definition.source_id == "s0":
                raise TimeoutError("secret URL")
            if self.definition.source_id == "s1":
                raise ValueError("bad parser payload")
            return [article(self.definition, self.definition.source_id)]

        async def close(self):
            closed[self.definition.source_id] = closed.get(self.definition.source_id, 0) + 1

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry(definitions),
        registry_version="test-v1",
        provider_factory=Provider,
    ).run("scheduled:one")

    assert total_peak <= 6 and host_peak <= 2
    assert result.articles_inserted == 6 and result.errors == 2
    assert set(result.rejection_reasons) == {"network_error", "parser_error"}
    assert closed == {definition.source_id: 1 for definition in definitions}


async def test_run_claim_rerun_idempotency_and_stale_lease(maker):
    definition = source("one")
    calls = 0

    class Provider:
        def __init__(self, _definition):
            pass

        async def fetch_articles(self, _groups):
            nonlocal calls
            calls += 1
            return [article(definition, "same")]

        async def close(self):
            pass

    kwargs = dict(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="test-v1",
        provider_factory=Provider,
    )
    first, second = await asyncio.gather(
        RetrievalOrchestrator(**kwargs).run("same"), RetrievalOrchestrator(**kwargs).run("same")
    )
    assert sorted((first.status, second.status)) == ["already_running", "completed"]
    rerun = await RetrievalOrchestrator(**kwargs).run("same")
    assert rerun.status == "already_completed" and rerun.articles_inserted == 0
    assert calls == 1
    other = await RetrievalOrchestrator(**kwargs).run("other")
    assert other.status == "completed" and other.database_duplicates == 1

    async with maker() as session:
        stale = NewsRetrievalRun(
            run_key="stale",
            status="running",
            registry_version="test-v1",
            started_at=datetime.utcnow() - timedelta(minutes=66),
            lease_owner="old",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        session.add(stale)
        await session.commit()
    reclaimed = await RetrievalOrchestrator(**kwargs).run("stale")
    assert reclaimed.status == "completed"


async def test_provenance_and_duplicate_counters_are_separate(maker):
    definition = source("provenance")
    duplicate = article(definition, "duplicate")

    class Provider:
        def __init__(self, _definition):
            pass

        async def fetch_articles(self, _groups):
            return [duplicate, duplicate, article(definition, "unique")]

        async def close(self):
            pass

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="test-v1",
        provider_factory=Provider,
    ).run("provenance")
    assert result.within_run_duplicates == 1 and result.database_duplicates == 0
    async with maker() as session:
        rows = list((await session.scalars(select(NewsArticleRaw))).all())
    assert len(rows) == 2
    assert all(
        (
            row.source_id,
            row.source_class,
            row.source_domains,
            row.source_countries,
            row.registry_version,
            row.retrieved_at,
        )
        == ("provenance", "official", ["regulation"], ["de"], "test-v1", datetime(2026, 7, 16, 12))
        for row in rows
    )


async def test_real_rss_failure_preserves_fetch_code_bytes_and_circuit(maker):
    definition = source("real")

    class Fetcher:
        async def fetch(self, _source):
            return FetchResult(failure_code=FetchFailureCode.OVERSIZED_RESPONSE, response_bytes=99)

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="injected-v2",
        provider_factory=lambda item: RSSProvider(item, Fetcher(), registry_version="injected-v2"),
    ).run("real-failure")
    assert result.rejection_reasons == {"oversized_response": 1}
    assert result.response_bytes == 99
    assert result.source_results[0].status == "failed"


async def test_provider_construction_and_close_failures_do_not_strand_run(maker):
    definitions = (source("construct"), source("close", "close.test"))

    class Provider:
        async def fetch_articles(self, _groups):
            return []

        async def close(self):
            raise RuntimeError("close secret")

    def factory(definition):
        if definition.source_id == "construct":
            raise RuntimeError("constructor secret")
        return Provider()

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry(definitions),
        registry_version="v",
        provider_factory=factory,
    ).run("lifecycle")
    assert result.status == "completed"
    assert {item.source_id: item.status for item in result.source_results} == {
        "construct": "failed",
        "close": "completed",
    }


def test_legacy_providers_are_registry_configuration(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "configured")
    monkeypatch.setenv("GDELT_ENABLED", "true")
    configured = configured_registry(SourceRegistry(()))
    assert [(item.source_id, item.adapter) for item in configured.enabled()] == [
        ("gdelt", AdapterType.GDELT),
        ("newsapi", AdapterType.NEWSAPI),
    ]
