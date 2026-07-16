"""Tests for Celery tasks."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from procuresignal.enrichment import (
    DeterministicAnalysis,
    EnrichmentMetrics,
    EnrichmentOutput,
    EnrichmentPipeline,
    EnrichmentPolicy,
    EnrichmentRunResult,
)
from procuresignal.models import Base, NewsArticleRaw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import worker.tasks as tasks
from worker.main import app
from worker.tasks import (
    enrich_articles_task,
    health_check_task,
    normalize_articles_task,
    personalize_feeds_task,
    prune_retention_task,
    retrieve_news_task,
)


def test_health_check_task() -> None:
    """Health check should return a healthy status payload."""
    result = health_check_task()

    assert result["status"] == "healthy"
    assert result["worker"]
    assert "timestamp" in result


def test_task_names_and_retry_config() -> None:
    """Tasks should be registered with the expected names and retry policy."""
    assert retrieve_news_task.name == "worker.tasks.retrieve_news_task"
    assert normalize_articles_task.name == "worker.tasks.normalize_articles_task"
    assert enrich_articles_task.name == "worker.tasks.enrich_articles_task"
    assert personalize_feeds_task.name == "worker.tasks.personalize_feeds_task"
    assert prune_retention_task.name == "worker.tasks.prune_retention_task"

    assert retrieve_news_task.max_retries == 3
    assert normalize_articles_task.max_retries == 3
    assert enrich_articles_task.max_retries == 2
    assert personalize_feeds_task.max_retries == 2
    assert prune_retention_task.max_retries == 2


def test_retrieve_task_preserves_legacy_and_adds_audit_metrics(monkeypatch) -> None:
    class Result:
        status = "completed"
        run_id = 42
        registry_version = "sources-v1"
        articles_fetched = 7
        articles_inserted = 5
        duplicates = 2
        errors = 1
        within_run_duplicates = 1
        database_duplicates = 1
        rejection_reasons = {"parser_error": 1}
        response_bytes = 1234
        latency_ms = 15
        circuit_state = {"ecb_press": "closed"}
        next_poll_at = datetime(2026, 7, 16, 13)
        source_results = ()

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            assert kwargs["registry_version"] == "sources-v1"

        async def run(self, run_key):
            assert run_key.startswith("scheduled:")
            return Result()

    monkeypatch.setattr(tasks, "RetrievalOrchestrator", FakeOrchestrator)
    result = retrieve_news_task.run()
    assert {
        "status",
        "articles_fetched",
        "articles_inserted",
        "duplicates",
        "errors",
        "providers",
        "timestamp",
    } <= result.keys()
    assert result["run_id"] == 42 and result["within_run_duplicates"] == 1
    assert result["rejection_reasons"] == {"parser_error": 1}


def test_celery_routes_and_schedule() -> None:
    """Celery should route periodic work onto the correct queues."""
    assert app.conf.task_routes["worker.tasks.retrieve_news_task"]["queue"] == "retrieval"
    assert app.conf.task_routes["worker.tasks.normalize_articles_task"]["queue"] == "processing"
    assert app.conf.task_routes["worker.tasks.enrich_articles_task"]["queue"] == "enrichment"
    assert app.conf.task_routes["worker.tasks.personalize_feeds_task"]["queue"] == "personalization"
    assert app.conf.task_routes["worker.tasks.prune_retention_task"]["queue"] == "default"

    schedule = app.conf.beat_schedule
    assert schedule["retrieve-news-every-6-hours"]["options"]["queue"] == "retrieval"
    assert schedule["normalize-articles-every-2-hours"]["options"]["queue"] == "processing"
    assert schedule["enrich-articles-every-2-hours"]["options"]["queue"] == "enrichment"
    assert schedule["personalize-feeds-every-hour"]["options"]["queue"] == "personalization"
    assert schedule["prune-retention-daily"]["task"] == "worker.tasks.prune_retention_task"
    assert schedule["prune-retention-daily"]["options"]["queue"] == "default"


def test_generate_risk_events_task_is_exported() -> None:
    from worker.tasks import __all__

    assert "generate_risk_events_task" in __all__
    assert "prune_retention_task" in __all__


def test_enrichment_task_exposes_route_and_savings_metrics(monkeypatch) -> None:
    """The task result keeps legacy counts and adds route-level cost metrics."""
    normalized = [SimpleNamespace(id=1)]
    metrics = EnrichmentMetrics(
        cached=2,
        deterministic=3,
        llm=1,
        skipped=4,
        deferred=1,
        failed=2,
        cache_misses=8,
        llm_calls=1,
        llm_tokens=321,
        avoided_llm_calls=9,
    )

    class FakeSession:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    @asynccontextmanager
    async def fake_session_scope():
        yield FakeSession()

    async def fake_normalize(*args, **kwargs):
        return {"raw_articles": normalized, "normalized_articles": normalized}

    class FakePipeline:
        def __init__(self, *, policy, llm_client_factory):
            self.policy = policy
            self.llm_client_factory = llm_client_factory

        async def process_raw_articles(self, session, articles, **_kwargs):
            assert articles == normalized
            return EnrichmentRunResult(saved=6, metrics=metrics, already_processed=2)

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "_normalize_articles", fake_normalize)
    monkeypatch.setattr(tasks, "EnrichmentPipeline", FakePipeline)

    result = enrich_articles_task.run()

    assert result["status"] == "success"
    assert result["enriched_count"] == 6
    assert result["skipped_count"] == 6
    assert result["error_count"] == 2
    assert result["routes"] == {
        "cached": 2,
        "deterministic": 3,
        "llm": 1,
        "skipped": 4,
        "deferred": 1,
        "failed": 2,
        "cache_misses": 8,
    }
    assert result["llm_calls"] == 1
    assert result["llm_tokens"] == 321
    assert result["avoided_llm_calls"] == 9
    assert "timestamp" in result


def test_enrichment_task_does_not_construct_openai_before_pipeline_routes(monkeypatch) -> None:
    """Missing OpenAI configuration must not block local/cache-only processing."""
    normalized = [SimpleNamespace(id=1)]
    metrics = EnrichmentMetrics(deterministic=1, avoided_llm_calls=1)

    class FakeSession:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    @asynccontextmanager
    async def fake_session_scope():
        yield FakeSession()

    async def fake_normalize(*args, **kwargs):
        return {"raw_articles": normalized, "normalized_articles": normalized}

    class FakePipeline:
        def __init__(self, *, policy, llm_client_factory):
            assert callable(llm_client_factory)
            self.llm_client_factory = llm_client_factory

        async def process_raw_articles(self, session, articles, **_kwargs):
            # A deterministic-only run never asks the factory for a client.
            return EnrichmentRunResult(saved=1, metrics=metrics)

    def forbidden_client():
        raise AssertionError("OpenAI client was eagerly constructed")

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "_normalize_articles", fake_normalize)
    monkeypatch.setattr(tasks, "EnrichmentPipeline", FakePipeline)
    monkeypatch.setattr(tasks, "OpenAILLMClient", forbidden_client)

    result = enrich_articles_task.run()

    assert result["enriched_count"] == 1
    assert result["routes"]["deterministic"] == 1


def test_enrichment_candidate_cap_does_not_starve_older_eligible_rows(tmp_path) -> None:
    """Terminal/processed newest rows must not consume the scheduled batch cap."""

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'selection.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as session:
            rows = []
            for index in range(25):
                row = NewsArticleRaw(
                    provider="test",
                    provider_article_id=str(index),
                    query_group="general",
                    ingest_hash=str(index),
                    title=f"Article {index}",
                    article_url=f"https://example.test/{index}",
                    source_name="Example",
                    published_at=now,
                    ingested_at=now - timedelta(minutes=index),
                    language="en",
                    enrichment_status="skipped" if index < 20 else None,
                )
                rows.append(row)
            session.add_all(rows)
            await session.commit()
            selected = await tasks._load_enrichment_candidates(session, hours_back=12, limit=5)
            assert [row.provider_article_id for row in selected] == ["20", "21", "22", "23", "24"]
        await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_enrichment_normalization_pages_past_unmarked_quality_rejects(
    monkeypatch, tmp_path
) -> None:
    """Newest rejects beyond the cap cannot hide older valid candidates."""

    async def fake_normalize(article):
        return None if article.title.startswith("Reject") else article

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quality.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as session:
            rows = []
            for index in range(28):
                rows.append(
                    NewsArticleRaw(
                        provider="test",
                        provider_article_id=str(index),
                        query_group="general",
                        ingest_hash=f"quality-{index}",
                        title=f"{'Reject' if index < 25 else 'Valid'} {index}",
                        article_url=f"https://example.test/quality/{index}",
                        source_name="Example",
                        published_at=now,
                        ingested_at=now - timedelta(minutes=index),
                        language="en",
                    )
                )
            session.add_all(rows)
            await session.commit()
            result = await tasks._normalize_articles(
                session, hours_back=12, limit=3, enrichment_candidates=True
            )
            assert [row.id for row in result["normalized_articles"]] == [
                rows[25].id,
                rows[26].id,
                rows[27].id,
            ]
            assert result["quality_failures"] == 25
            assert all(row.enrichment_status == "quality_rejected" for row in rows[:25])
        await engine.dispose()

    monkeypatch.setattr(tasks.ArticleNormalizer, "normalize", fake_normalize)
    import asyncio

    asyncio.run(run())


def test_transient_normalization_error_backs_off_and_older_work_progresses(
    monkeypatch, tmp_path
) -> None:
    calls = {"Transient": 0}

    async def fake_normalize(article):
        if article.title == "Transient":
            calls["Transient"] += 1
            if calls["Transient"] == 1:
                raise RuntimeError("temporary parser failure")
        return article

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as session:
            newest = NewsArticleRaw(
                provider="test",
                provider_article_id="new",
                query_group="general",
                ingest_hash="retry-new",
                title="Transient",
                article_url="https://x/new",
                source_name="Example",
                published_at=now,
                ingested_at=now,
                language="en",
            )
            older = NewsArticleRaw(
                provider="test",
                provider_article_id="old",
                query_group="general",
                ingest_hash="retry-old",
                title="Older valid",
                article_url="https://x/old",
                source_name="Example",
                published_at=now,
                ingested_at=now - timedelta(hours=1),
                language="en",
            )
            session.add_all([newest, older])
            await session.commit()
            first = await tasks._normalize_articles(
                session, hours_back=12, limit=1, enrichment_candidates=True
            )
            assert [row.id for row in first["normalized_articles"]] == [older.id]
            assert newest.enrichment_status == "normalization_retry"
            assert newest.enrichment_attempt_count == 1
            assert newest.enrichment_next_attempt_at > now
            immediate = await tasks._load_enrichment_candidates(session, hours_back=12, limit=5)
            assert newest not in immediate
            newest.enrichment_next_attempt_at = now - timedelta(seconds=1)
            await session.commit()
            retried = await tasks._normalize_articles(
                session, hours_back=12, limit=1, enrichment_candidates=True
            )
            assert [row.id for row in retried["normalized_articles"]] == [newest.id]
        await engine.dispose()

    monkeypatch.setattr(tasks.ArticleNormalizer, "normalize", fake_normalize)
    import asyncio

    asyncio.run(run())


def test_aged_deferred_candidate_remains_due_but_does_not_hot_loop(tmp_path) -> None:
    class Analyzer:
        def analyze(self, *_args, **_kwargs):
            return DeterministicAnalysis(
                EnrichmentOutput(
                    summary="Bosch outlook remains relevant to procurement.",
                    category="general",
                ),
                0.9,
                0.4,
            )

    class Client:
        model = "unused"
        total_tokens_used = 0

        async def call(self, *_args, **_kwargs):
            raise AssertionError("budget-deferred route called LLM")

    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deferred.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as session:
            aged = NewsArticleRaw(
                provider="test",
                provider_article_id="aged",
                query_group="supplier_risk",
                ingest_hash="aged-deferred",
                title="Bosch outlook in Germany",
                article_url="https://x/aged",
                source_name="Example",
                published_at=now,
                ingested_at=now - timedelta(days=30),
                language="en",
                enrichment_status="deferred",
                enrichment_attempt_count=1,
                enrichment_next_attempt_at=now - timedelta(minutes=1),
            )
            session.add(aged)
            await session.commit()
            due = await tasks._load_enrichment_candidates(session, hours_back=12, limit=5)
            assert due == [aged]

            result = await EnrichmentPipeline(
                Client(),
                policy=EnrichmentPolicy(max_llm_tokens=1),
                deterministic_enricher=Analyzer(),
            ).process_raw_articles(session, [aged])
            await session.refresh(aged)
            assert result.metrics.deferred == 1
            assert aged.enrichment_attempt_count == 2
            assert aged.enrichment_next_attempt_at > datetime.utcnow()
            assert aged not in await tasks._load_enrichment_candidates(
                session, hours_back=12, limit=5
            )
        await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_normalize_task_commits_quality_reject_before_session_closes(monkeypatch, tmp_path) -> None:
    database = tmp_path / "normalize-commit.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with maker() as session:
            now = datetime.utcnow()
            session.add(
                NewsArticleRaw(
                    provider="test",
                    provider_article_id="reject",
                    query_group="general",
                    ingest_hash="task-reject",
                    title="Rejected",
                    article_url="https://x/reject",
                    source_name="Example",
                    published_at=now,
                    ingested_at=now,
                    language="en",
                )
            )
            await session.commit()

    @asynccontextmanager
    async def real_scope():
        async with maker() as session:
            yield session

    async def reject(_article):
        return None

    import asyncio

    asyncio.run(prepare())
    monkeypatch.setattr(tasks, "session_scope", real_scope)
    monkeypatch.setattr(tasks.ArticleNormalizer, "normalize", reject)
    result = normalize_articles_task.run()
    assert result["quality_failures"] == 1

    async def verify():
        async with maker() as session:
            row = await session.scalar(select(NewsArticleRaw))
            assert row.enrichment_status == "quality_rejected"
            assert row.enrichment_lease_owner is None
        await engine.dispose()

    asyncio.run(verify())


def test_enrich_task_commits_normalization_retry_and_reports_error(monkeypatch, tmp_path) -> None:
    database = tmp_path / "enrich-error-commit.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with maker() as session:
            now = datetime.utcnow()
            session.add(
                NewsArticleRaw(
                    provider="test",
                    provider_article_id="error",
                    query_group="general",
                    ingest_hash="task-error",
                    title="Transient",
                    article_url="https://x/error",
                    source_name="Example",
                    published_at=now,
                    ingested_at=now,
                    language="en",
                )
            )
            await session.commit()

    @asynccontextmanager
    async def real_scope():
        async with maker() as session:
            yield session

    async def fail(_article):
        raise RuntimeError("temporary normalization failure")

    import asyncio

    asyncio.run(prepare())
    monkeypatch.setattr(tasks, "session_scope", real_scope)
    monkeypatch.setattr(tasks.ArticleNormalizer, "normalize", fail)
    result = enrich_articles_task.run()
    assert result["enriched_count"] == 0
    assert result["error_count"] == 1

    async def verify():
        async with maker() as session:
            row = await session.scalar(select(NewsArticleRaw))
            assert row.enrichment_status == "normalization_retry"
            assert row.enrichment_attempt_count == 1
            assert row.enrichment_next_attempt_at > datetime.utcnow()
            assert row.enrichment_lease_owner is None
        await engine.dispose()

    asyncio.run(verify())


def test_overlapping_workers_claim_once_before_llm(monkeypatch, tmp_path) -> None:
    """A committed lease prevents a second worker from paying for the same row."""

    class Analyzer:
        def analyze(self, *_args, **_kwargs):
            return DeterministicAnalysis(
                EnrichmentOutput(
                    summary="Ambiguous but relevant procurement update.", category="general"
                ),
                0.9,
                0.4,
            )

    class Client:
        model = "fake"
        total_tokens_used = 0

        def __init__(self):
            self.calls = 0

        async def call(self, *_args, **_kwargs):
            self.calls += 1
            self.total_tokens_used += 20
            return EnrichmentOutput(
                summary="Recorded LLM result for the claimed procurement article.",
                category="general",
            ).model_dump_json()

    created: list[Client] = []

    def factory():
        client = Client()
        created.append(client)
        return client

    async def normalize(article):
        return article

    async def run():
        database = tmp_path / "claim-concurrency.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database}", connect_args={"timeout": 10}
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as seed:
            seed.add(
                NewsArticleRaw(
                    provider="test",
                    provider_article_id="one",
                    query_group="supplier_risk",
                    ingest_hash="claim-once",
                    title="Ambiguous supplier outlook",
                    article_url="https://x/claim",
                    source_name="Example",
                    published_at=now,
                    ingested_at=now,
                    language="en",
                )
            )
            await seed.commit()

        async with maker() as first, maker() as second:
            first_result, second_result = await asyncio.gather(
                tasks._normalize_articles(
                    first,
                    hours_back=12,
                    limit=1,
                    enrichment_candidates=True,
                    claim_owner="worker-one",
                ),
                tasks._normalize_articles(
                    second,
                    hours_back=12,
                    limit=1,
                    enrichment_candidates=True,
                    claim_owner="worker-two",
                ),
            )
            winner_session, winner_owner, winner = (
                (first, "worker-one", first_result)
                if first_result["normalized_articles"]
                else (second, "worker-two", second_result)
            )
            assert sorted(
                [
                    len(first_result["normalized_articles"]),
                    len(second_result["normalized_articles"]),
                ]
            ) == [0, 1]
            result = await EnrichmentPipeline(
                llm_client_factory=factory, deterministic_enricher=Analyzer()
            ).process_raw_articles(
                winner_session, winner["normalized_articles"], claim_owner=winner_owner
            )
            assert result.metrics.llm == 1

        async with maker() as verify:
            assert await verify.scalar(select(func.count()).select_from(NewsArticleProcessed)) == 1
            raw = await verify.scalar(select(NewsArticleRaw))
            assert raw.enrichment_status == "completed"
            assert raw.enrichment_lease_owner is None
        assert len(created) == 1 and created[0].calls == 1
        await engine.dispose()

    import asyncio

    from procuresignal.models import NewsArticleProcessed
    from sqlalchemy import func

    monkeypatch.setattr(tasks.ArticleNormalizer, "normalize", normalize)
    asyncio.run(run())


def test_stale_lease_is_reclaimed_and_failure_release_is_durable(tmp_path) -> None:
    async def run():
        database = tmp_path / "stale-lease.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.utcnow()
        async with maker() as session:
            raw = NewsArticleRaw(
                provider="test",
                provider_article_id="stale",
                query_group="general",
                ingest_hash="stale-lease",
                title="Stale lease",
                article_url="https://x/stale",
                source_name="Example",
                published_at=now,
                ingested_at=now,
                language="en",
                enrichment_status="processing",
                enrichment_lease_owner="dead-worker",
                enrichment_lease_expires_at=now - timedelta(minutes=1),
            )
            session.add(raw)
            await session.commit()
            claimed = await tasks._claim_enrichment_candidates(
                session, limit=1, owner="replacement"
            )
            assert claimed == [raw]
            assert raw.enrichment_lease_owner == "replacement"
            await tasks._release_enrichment_claims_after_failure(session, owner="replacement")

        async with maker() as verify:
            persisted = await verify.scalar(select(NewsArticleRaw))
            assert persisted.enrichment_status == "enrichment_retry"
            assert persisted.enrichment_attempt_count == 1
            assert persisted.enrichment_next_attempt_at > datetime.utcnow()
            assert persisted.enrichment_lease_owner is None
        await engine.dispose()

    import asyncio

    asyncio.run(run())
