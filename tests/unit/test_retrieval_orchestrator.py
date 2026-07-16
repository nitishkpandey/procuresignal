import asyncio
from datetime import datetime, timedelta

import pytest
from procuresignal.models import (
    Base,
    NewsArticleRaw,
    NewsRetrievalCircuit,
    NewsRetrievalRun,
    NewsRetrievalSourceOutcome,
)
from procuresignal.retrieval.audit import RetrievalAuditRepository
from procuresignal.retrieval.base import (
    FetchFailureCode,
    FetchResult,
    RawArticle,
    RetrievalFetchError,
)
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.orchestrator import RetrievalOrchestrator, configured_registry
from procuresignal.retrieval.providers.gdelt import GDELTProvider
from procuresignal.retrieval.providers.newsapi import NewsAPIProvider
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.registry import (
    AdapterType,
    ProcurementDomain,
    SourceClass,
    SourceDefinition,
    SourceRegistry,
)
from procuresignal.retrieval.security import URLSafetyPolicy
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
    assert "completed" in (first.status, second.status)
    assert {first.status, second.status} <= {"completed", "already_running", "already_completed"}
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


@pytest.mark.parametrize("provider_type", [NewsAPIProvider, GDELTProvider])
async def test_legacy_adapters_use_safe_fetcher_and_authoritative_bytes(monkeypatch, provider_type):
    monkeypatch.setenv("NEWSAPI_KEY", "top-secret")
    configured = configured_registry(SourceRegistry(()))
    if provider_type is GDELTProvider:
        monkeypatch.setenv("GDELT_ENABLED", "true")
        configured = configured_registry(SourceRegistry(()))
        definition = next(item for item in configured.enabled() if item.source_id == "gdelt")
    else:
        definition = next(item for item in configured.enabled() if item.source_id == "newsapi")
    calls = []

    class Fetcher:
        async def fetch(self, source, params=None):
            calls.append((source.endpoint_url, params))
            return FetchResult(content=b'{"status":"ok","articles":[]}', response_bytes=31)

        async def aclose(self):
            pass

    provider = provider_type(source=definition, fetcher=Fetcher())
    provider._get = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("generic client used")
    )
    await provider.fetch_articles(["regulatory"])
    assert calls and provider.last_response_bytes == 31 * len(calls)
    assert all("top-secret" not in url for url, _params in calls)
    if provider_type is NewsAPIProvider:
        assert all(params["apiKey"] == "top-secret" for _url, params in calls)


async def test_newsapi_safe_fetch_failure_is_structured(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "secret")
    definition = next(
        item
        for item in configured_registry(SourceRegistry(())).enabled()
        if item.source_id == "newsapi"
    )

    class Fetcher:
        async def fetch(self, _source, _params=None):
            return FetchResult(failure_code=FetchFailureCode.CIRCUIT_OPEN)

        async def aclose(self):
            pass

    with pytest.raises(Exception) as error:
        await NewsAPIProvider(source=definition, fetcher=Fetcher()).fetch_articles(["regulatory"])
    assert getattr(error.value, "result").failure_code is FetchFailureCode.CIRCUIT_OPEN
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("adapter", [AdapterType.NEWSAPI, AdapterType.GDELT])
async def test_malformed_legacy_json_is_durable_parser_failure(maker, monkeypatch, adapter):
    monkeypatch.setenv("NEWSAPI_KEY", "secret")
    monkeypatch.setenv("GDELT_ENABLED", "true")
    definition = next(
        item
        for item in configured_registry(SourceRegistry(())).enabled()
        if item.adapter is adapter
    )
    malformed = b'{"secret-body":'

    class Fetcher:
        async def fetch(self, _source, _params=None):
            return FetchResult(content=malformed, response_bytes=len(malformed))

        async def aclose(self):
            pass

    def factory(item):
        provider_type = NewsAPIProvider if item.adapter is AdapterType.NEWSAPI else GDELTProvider
        return provider_type(source=item, fetcher=Fetcher())

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="parser-v1",
        provider_factory=factory,
    ).run(f"malformed-{adapter.value}")

    assert result.status == "completed"
    assert result.articles_inserted == 0
    assert result.rejection_reasons == {"parser_error": 1}
    assert result.response_bytes == len(malformed)
    assert result.source_results[0].status == "failed"
    assert result.source_results[0].failure_code == "parser_error"
    assert "secret-body" not in repr(result)


async def test_five_parser_failures_open_circuit_and_half_open_success_closes(maker):
    definition = source("parser_circuit")
    should_fail = True

    class Provider:
        async def fetch_articles(self, _groups):
            if should_fail:
                raise RetrievalFetchError(
                    FetchResult(failure_code=FetchFailureCode.PARSER_ERROR, response_bytes=7)
                )
            return []

        async def close(self):
            pass

    orchestrator = RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="circuit-v1",
        provider_factory=lambda _item: Provider(),
    )
    for attempt in range(5):
        result = await orchestrator.run(f"parser-circuit-{attempt}")
        assert result.rejection_reasons == {"parser_error": 1}

    async with maker() as session:
        circuit = await session.scalar(
            select(NewsRetrievalCircuit).where(
                NewsRetrievalCircuit.source_id == definition.source_id
            )
        )
        assert circuit is not None
        assert circuit.failure_count == 5
        assert circuit.open_until is not None
        circuit.open_until = datetime.utcnow() - timedelta(seconds=1)
        circuit.probe_owner = orchestrator.owner
        circuit.probe_expires_at = datetime.utcnow() + timedelta(minutes=65)
        await session.commit()

    should_fail = False
    success = await orchestrator.run("parser-circuit-recovery")
    assert success.source_results[0].status == "completed"
    async with maker() as session:
        recovered = await session.scalar(
            select(NewsRetrievalCircuit).where(
                NewsRetrievalCircuit.source_id == definition.source_id
            )
        )
        assert recovered is not None
        assert recovered.failure_count == 0
        assert recovered.open_until is None


async def test_half_open_owner_completes_real_newsapi_multi_request_run(maker, monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "secret")
    definition = next(
        item
        for item in configured_registry(SourceRegistry(())).enabled()
        if item.adapter is AdapterType.NEWSAPI
    )
    old = datetime.utcnow() - timedelta(minutes=31)
    async with maker() as owner_session, maker() as other_session:
        owner_repo = RetrievalAuditRepository(owner_session)
        other_repo = RetrievalAuditRepository(other_session)
        for _ in range(5):
            await owner_repo.record_circuit_failure(definition.source_id, old)

        calls = 0
        owner_fetcher = SafeFetcher(
            policy=URLSafetyPolicy(),
            circuit_store=owner_repo,
            owner="probe-owner",
            defer_success=True,
        )

        async def valid_attempt(_source, _params=None):
            nonlocal calls
            calls += 1
            body = b'{"status":"ok","articles":[]}'
            return FetchResult(content=body, response_bytes=len(body))

        owner_fetcher._attempt = valid_attempt
        probe = await owner_fetcher.fetch(definition)
        assert probe.ok
        provider = NewsAPIProvider(api_key="secret", source=definition, fetcher=owner_fetcher)
        await provider.fetch_articles(["regulatory"])
        assert calls == 7

        denied_fetcher = SafeFetcher(
            policy=URLSafetyPolicy(),
            circuit_store=other_repo,
            owner="other-owner",
            defer_success=True,
        )
        denied_fetcher._attempt = valid_attempt
        denied = await denied_fetcher.fetch(definition)
        assert denied.failure_code is FetchFailureCode.CIRCUIT_OPEN
        assert calls == 7

        assert await owner_repo.record_circuit_success(definition.source_id, "probe-owner")
        circuit = await owner_session.scalar(
            select(NewsRetrievalCircuit).where(
                NewsRetrievalCircuit.source_id == definition.source_id
            )
        )
        assert circuit is not None
        assert circuit.failure_count == 0
        await provider.close()
        await denied_fetcher.aclose()


@pytest.mark.parametrize("stolen", ["source", "run"])
async def test_lease_theft_before_persistence_rolls_back_rows(maker, stolen):
    definition = source(f"stolen_{stolen}")

    class Provider:
        async def fetch_articles(self, _groups):
            async with maker() as thief:
                if stolen == "source":
                    outcome = await thief.scalar(select(NewsRetrievalSourceOutcome))
                    assert outcome is not None
                    outcome.lease_owner = "thief"
                else:
                    run = await thief.scalar(select(NewsRetrievalRun))
                    assert run is not None
                    run.lease_owner = "thief"
                await thief.commit()
            return [article(definition, stolen)]

        async def close(self):
            pass

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="fence-v1",
        provider_factory=lambda _item: Provider(),
        owner="original",
    ).run(f"stolen-{stolen}")
    assert result.status == "lease_lost"
    assert result.articles_inserted == 0
    assert result.source_results[0].status == "lease_lost"
    async with maker() as session:
        assert await session.scalar(select(NewsArticleRaw)) is None


async def test_failed_run_completion_fence_is_not_reported_completed(maker, monkeypatch):
    definition = source("run_completion_fence")

    class Provider:
        async def fetch_articles(self, _groups):
            return []

        async def close(self):
            pass

    async def rejected_completion(self, *args, **kwargs):
        return False

    monkeypatch.setattr(RetrievalAuditRepository, "complete_run", rejected_completion)
    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="fence-v1",
        provider_factory=lambda _item: Provider(),
        owner="original",
    ).run("run-completion-fence")
    assert result.status == "lease_lost"
    assert result.rejection_reasons == {"lease_lost": 1}


async def test_same_retry_owner_resumes_live_run_lease(maker):
    definition = source("retry_owner")
    first = RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="retry-v1",
        owner="celery-task-id",
    )
    run, acquired, _ = await first._claim("retry-run", datetime.utcnow())
    assert acquired
    retry = RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="retry-v1",
        owner="celery-task-id",
    )
    resumed, reacquired, status = await retry._claim("retry-run", datetime.utcnow())
    assert resumed.id == run.id
    assert reacquired and status == "running"


async def test_retry_aggregates_completed_prior_source_once(maker):
    first_source = source("retry_a", "a.test")
    second_source = source("retry_b", "b.test")
    now = datetime.utcnow()
    async with maker() as session:
        run = NewsRetrievalRun(
            run_key="aggregate-retry",
            status="running",
            registry_version="retry-v1",
            lease_owner="celery-task-id",
            lease_expires_at=now + timedelta(minutes=60),
            started_at=now,
        )
        session.add(run)
        await session.flush()
        session.add(
            NewsRetrievalSourceOutcome(
                run_id=run.id,
                source_id=first_source.source_id,
                status="completed",
                attempted_count=1,
                fetched_count=3,
                accepted_count=3,
                inserted_count=2,
                duplicate_count=1,
                started_at=now,
                finished_at=now,
            )
        )
        await session.commit()

    class Provider:
        def __init__(self, definition):
            self.definition = definition

        async def fetch_articles(self, _groups):
            return [article(self.definition, "retry-b")]

        async def close(self):
            pass

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((first_source, second_source)),
        registry_version="retry-v1",
        provider_factory=Provider,
        owner="celery-task-id",
    ).run("aggregate-retry")
    assert result.status == "completed"
    assert result.articles_fetched == 4
    assert result.articles_inserted == 3
    assert result.duplicates == 1
    assert {item.source_id for item in result.source_results} == {"retry_a", "retry_b"}


async def test_retry_after_all_sources_complete_finalizes_prior_totals(maker):
    definition = source("already_done")
    now = datetime.utcnow()
    async with maker() as session:
        run = NewsRetrievalRun(
            run_key="finalize-retry",
            status="running",
            registry_version="retry-v1",
            lease_owner="celery-task-id",
            lease_expires_at=now + timedelta(minutes=60),
            started_at=now,
        )
        session.add(run)
        await session.flush()
        session.add(
            NewsRetrievalSourceOutcome(
                run_id=run.id,
                source_id=definition.source_id,
                status="completed",
                attempted_count=1,
                fetched_count=5,
                accepted_count=4,
                inserted_count=3,
                duplicate_count=1,
                rejected_count=1,
                started_at=now,
                finished_at=now,
            )
        )
        await session.commit()

    class ForbiddenProvider:
        def __init__(self, _definition):
            raise AssertionError("completed source was fetched again")

    result = await RetrievalOrchestrator(
        session_factory=maker,
        registry=SourceRegistry((definition,)),
        registry_version="retry-v1",
        provider_factory=ForbiddenProvider,
        owner="celery-task-id",
    ).run("finalize-retry")
    assert result.status == "completed"
    assert (result.articles_fetched, result.articles_inserted, result.duplicates) == (5, 3, 1)
