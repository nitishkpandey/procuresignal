"""Tests for Celery tasks."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from procuresignal.enrichment import EnrichmentMetrics, EnrichmentRunResult
from procuresignal.models import Base, NewsArticleRaw
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

    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    async def fake_normalize(*args, **kwargs):
        return {"raw_articles": normalized, "normalized_articles": normalized}

    class FakePipeline:
        def __init__(self, *, policy, llm_client_factory):
            self.policy = policy
            self.llm_client_factory = llm_client_factory

        async def process_raw_articles(self, session, articles):
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

    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    async def fake_normalize(*args, **kwargs):
        return {"raw_articles": normalized, "normalized_articles": normalized}

    class FakePipeline:
        def __init__(self, *, policy, llm_client_factory):
            assert callable(llm_client_factory)
            self.llm_client_factory = llm_client_factory

        async def process_raw_articles(self, session, articles):
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
                    enrichment_terminal_status="skipped" if index < 20 else None,
                )
                rows.append(row)
            session.add_all(rows)
            await session.commit()
            selected = await tasks._load_enrichment_candidates(session, hours_back=12, limit=5)
            assert [row.provider_article_id for row in selected] == ["20", "21", "22", "23", "24"]
        await engine.dispose()

    import asyncio

    asyncio.run(run())
