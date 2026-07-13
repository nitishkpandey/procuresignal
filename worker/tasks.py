"""Celery task definitions for background processing."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine

from procuresignal.config.database import session_scope
from procuresignal.enrichment import EnrichmentPipeline, EnrichmentPolicy, OpenAILLMClient
from procuresignal.jobs import RetentionPolicy, prune_expired_records
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, UserNewsPreference
from procuresignal.normalization import ArticleNormalizer
from procuresignal.personalization import PersonalizationPipeline
from procuresignal.retrieval import (
    ArticlePersistence,
    GDELTProvider,
    NewsAPIProvider,
    RawArticle,
    RSSProvider,
)
from procuresignal.risk_events.persistence import generate_risk_events
from sqlalchemy import desc, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.main import app
from worker.signal_tasks import process_article_for_signals

logger = logging.getLogger(__name__)

NEWSAPI_QUERIES = [
    "procurement supply chain",
    "supplier risk",
    "tariff changes",
    "logistics disruption",
    "regulatory compliance",
    "European business procurement",
]
GDELT_QUERY_GROUPS = [
    "supplier_risk",
    "logistics_disruption",
    "tariff_changes",
    "regulatory",
    "europe_business",
]
RSS_QUERY_GROUPS = ["supplier_risk", "regulatory", "logistics", "commodities"]

# Cap enrichment per run so a backlog cannot monopolize the shared LLM budget.
# The beat schedule drains the rest over subsequent runs.
_ENRICH_MAX_PER_RUN = 20


@dataclass(slots=True)
class _NormalizedArticleRecord:
    id: int
    provider: str
    provider_article_id: str | None
    query_group: str
    title: str
    description: str | None
    content_snippet: str | None
    article_url: str
    canonical_url: str | None
    source_name: str
    source_url: str | None
    published_at: datetime
    language: str
    raw_payload_json: dict[str, Any] | None


def _to_raw_article(article: NewsArticleRaw) -> RawArticle:
    return RawArticle(
        provider=article.provider,
        provider_article_id=article.provider_article_id,
        query_group=article.query_group,
        title=article.title,
        description=article.description,
        content_snippet=article.content_snippet,
        article_url=article.article_url,
        canonical_url=article.canonical_url,
        source_name=article.source_name,
        source_url=article.source_url,
        published_at=article.published_at,
        language=article.language,
        raw_payload_json=article.raw_payload_json,
    )


def _run_with_retry(task: Any, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Run an async task body, retrying with exponential backoff on failure."""
    try:
        return asyncio.run(coro_factory())
    except Exception as exc:
        raise task.retry(exc=exc, countdown=60 * (2**task.request.retries)) from exc


async def _load_recent_raw_articles(
    session: AsyncSession,
    *,
    hours_back: int,
    limit: int,
) -> list[NewsArticleRaw]:
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    now = datetime.utcnow()
    result = await session.execute(
        select(NewsArticleRaw)
        .where(
            NewsArticleRaw.ingested_at >= cutoff,
            NewsArticleRaw.enrichment_status.is_(None)
            | (
                NewsArticleRaw.enrichment_status.in_(("normalization_retry", "deferred"))
                & (NewsArticleRaw.enrichment_next_attempt_at <= now)
            ),
        )
        .order_by(desc(NewsArticleRaw.ingested_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def _load_enrichment_candidates(
    session: AsyncSession, *, hours_back: int, limit: int, exclude_ids: set[int] | None = None
) -> list[NewsArticleRaw]:
    """Load due unfinished candidates regardless of ingestion age."""
    del hours_back  # Enrichment eligibility is bounded by retention, not a recent-time window.
    now = datetime.utcnow()
    processed = exists().where(NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
    statement = (
        select(NewsArticleRaw)
        .where(~processed)
        .where(
            NewsArticleRaw.enrichment_status.is_(None)
            | (
                NewsArticleRaw.enrichment_status.in_(("normalization_retry", "deferred"))
                & (NewsArticleRaw.enrichment_next_attempt_at <= now)
            )
        )
        .order_by(desc(NewsArticleRaw.ingested_at))
        .limit(limit)
    )
    if exclude_ids:
        statement = statement.where(NewsArticleRaw.id.not_in(exclude_ids))
    result = await session.execute(statement)
    return list(result.scalars().all())


async def _normalize_articles(
    session: AsyncSession, *, hours_back: int, limit: int, enrichment_candidates: bool = False
) -> dict[str, Any]:
    raw_articles = (
        []
        if enrichment_candidates
        else await _load_recent_raw_articles(session, hours_back=hours_back, limit=limit)
    )
    normalized_articles: list[_NormalizedArticleRecord] = []
    quality_failures = 0
    errors = 0
    scanned_ids: set[int] = set()

    async def normalize_batch(batch: list[NewsArticleRaw]) -> None:
        nonlocal quality_failures, errors
        for article in batch:
            scanned_ids.add(article.id)
            try:
                normalized = await ArticleNormalizer.normalize(_to_raw_article(article))
                if normalized is None:
                    quality_failures += 1
                    article.enrichment_status = "quality_rejected"
                    article.enrichment_next_attempt_at = None
                    continue

                normalized_articles.append(
                    _NormalizedArticleRecord(
                        id=article.id,
                        provider=normalized.provider,
                        provider_article_id=normalized.provider_article_id,
                        query_group=normalized.query_group,
                        title=normalized.title,
                        description=normalized.description,
                        content_snippet=normalized.content_snippet,
                        article_url=normalized.article_url,
                        canonical_url=normalized.canonical_url,
                        source_name=normalized.source_name,
                        source_url=normalized.source_url,
                        published_at=normalized.published_at,
                        language=normalized.language,
                        raw_payload_json=normalized.raw_payload_json,
                    )
                )
            except Exception:
                errors += 1
                article.enrichment_attempt_count += 1
                delay_minutes = min(360, 15 * (2 ** (article.enrichment_attempt_count - 1)))
                article.enrichment_status = "normalization_retry"
                article.enrichment_next_attempt_at = datetime.utcnow() + timedelta(
                    minutes=delay_minutes
                )

    if enrichment_candidates:
        while len(normalized_articles) < limit:
            batch = await _load_enrichment_candidates(
                session,
                hours_back=hours_back,
                limit=limit - len(normalized_articles),
                exclude_ids=scanned_ids,
            )
            if not batch:
                break
            raw_articles.extend(batch)
            await normalize_batch(batch)
            await session.flush()
    else:
        await normalize_batch(raw_articles)

    return {
        "raw_articles": raw_articles,
        "normalized_articles": normalized_articles,
        "normalized_count": len(normalized_articles),
        "quality_failures": quality_failures,
        "errors": errors,
    }


@app.task(
    name="worker.tasks.retrieve_news_task",
    bind=True,
    max_retries=3,
    queue="retrieval",
    time_limit=3600,
)
def retrieve_news_task(self: Any) -> dict[str, Any]:
    """Retrieve news from all providers."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            providers = [
                ("newsapi", NewsAPIProvider(), NEWSAPI_QUERIES),
                ("rss", RSSProvider(), RSS_QUERY_GROUPS),
            ]
            # GDELT's free endpoint aggressively 429s and can stall retrieval for minutes;
            # opt in via GDELT_ENABLED=true only where a higher rate limit is available.
            if os.getenv("GDELT_ENABLED", "false").lower() == "true":
                providers.insert(1, ("gdelt", GDELTProvider(), GDELT_QUERY_GROUPS))
            provider_results: dict[str, Any] = {}
            total_fetched = 0
            total_inserted = 0
            total_duplicates = 0
            total_errors = 0

            for provider_name, provider, query_groups in providers:
                try:
                    articles = await provider.fetch_articles(query_groups)
                    inserted, duplicates, errors = await ArticlePersistence.save_articles(
                        session, articles
                    )
                    provider_results[provider_name] = {
                        "fetched": len(articles),
                        "inserted": inserted,
                        "duplicates": duplicates,
                        "errors": errors,
                    }
                    total_fetched += len(articles)
                    total_inserted += inserted
                    total_duplicates += duplicates
                    total_errors += errors
                except Exception as exc:
                    logger.exception("%s retrieval failed: %s", provider_name, exc)
                    provider_results[provider_name] = {"status": "error", "error": str(exc)}
                finally:
                    try:
                        await provider.close()
                    except Exception:
                        logger.exception("Failed to close %s provider", provider_name)

            return {
                "status": "success",
                "articles_fetched": total_fetched,
                "articles_inserted": total_inserted,
                "duplicates": total_duplicates,
                "errors": total_errors,
                "providers": provider_results,
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.normalize_articles_task",
    bind=True,
    max_retries=3,
    queue="processing",
    time_limit=3600,
)
def normalize_articles_task(self: Any) -> dict[str, Any]:
    """Normalize recently ingested raw articles."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            stats = await _normalize_articles(session, hours_back=24, limit=1000)
            return {
                "status": "success",
                "normalized_count": stats["normalized_count"],
                "quality_failures": stats["quality_failures"],
                "errors": stats["errors"],
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.enrich_articles_task",
    bind=True,
    max_retries=2,
    queue="enrichment",
    time_limit=3600,
)
def enrich_articles_task(self: Any) -> dict[str, Any]:
    """Enrich normalized raw articles with LLM summaries."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            stats = await _normalize_articles(
                session,
                hours_back=12,
                limit=_ENRICH_MAX_PER_RUN,
                enrichment_candidates=True,
            )
            normalized_articles = stats["normalized_articles"]

            if not normalized_articles:
                empty_routes = {
                    "cached": 0,
                    "deterministic": 0,
                    "llm": 0,
                    "skipped": 0,
                    "deferred": 0,
                    "failed": 0,
                    "cache_misses": 0,
                }
                return {
                    "status": "success",
                    "enriched_count": 0,
                    "skipped_count": len(stats["raw_articles"]),
                    "error_count": 0,
                    "reason": "no normalized articles available",
                    "routes": empty_routes,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                    "avoided_llm_calls": 0,
                    "timestamp": datetime.utcnow().isoformat(),
                }

            policy = EnrichmentPolicy.from_env()
            pipeline = EnrichmentPipeline(policy=policy, llm_client_factory=OpenAILLMClient)
            run_result = await pipeline.process_raw_articles(
                session,
                normalized_articles,
            )
            metrics = run_result.metrics
            return {
                "status": "success",
                "enriched_count": run_result.saved,
                "skipped_count": metrics.skipped + run_result.already_processed,
                "error_count": metrics.failed,
                "normalized_candidates": len(normalized_articles),
                "routes": {
                    "cached": metrics.cached,
                    "deterministic": metrics.deterministic,
                    "llm": metrics.llm,
                    "skipped": metrics.skipped,
                    "deferred": metrics.deferred,
                    "failed": metrics.failed,
                    "cache_misses": metrics.cache_misses,
                },
                "llm_calls": metrics.llm_calls,
                "llm_tokens": metrics.llm_tokens,
                "avoided_llm_calls": metrics.avoided_llm_calls,
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.personalize_feeds_task",
    bind=True,
    max_retries=2,
    queue="personalization",
    time_limit=1800,
)
def personalize_feeds_task(self: Any) -> dict[str, Any]:
    """Generate personalized feeds for all users with preferences."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            result = await session.execute(select(UserNewsPreference))
            users = list(result.scalars().all())

            pipeline = PersonalizationPipeline()
            feeds_generated = 0
            matched_articles = 0
            total_articles = 0

            for user in users:
                try:
                    feed_articles, matched, total = await pipeline.generate_feed(
                        session,
                        user.user_id,
                        limit=50,
                        days_back=7,
                    )
                    if feed_articles:
                        feeds_generated += 1
                    matched_articles += matched
                    total_articles += total
                except Exception as exc:
                    logger.exception(
                        "Failed to personalize feed for user %s: %s", user.user_id, exc
                    )

            return {
                "status": "success",
                "feeds_generated": feeds_generated,
                "matched_articles": matched_articles,
                "total_articles": total_articles,
                "users_processed": len(users),
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.generate_risk_events_task",
    bind=True,
    max_retries=2,
    queue="personalization",
    time_limit=1800,
)
def generate_risk_events_task(self: Any) -> dict[str, Any]:
    """Generate idempotent procurement risk events from processed articles."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            result = await generate_risk_events(session, days_back=7, limit=500)
            return {
                "status": "success",
                "created": result.created,
                "updated": result.updated,
                "scanned": result.scanned,
                "errors": result.errors,
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.prune_retention_task",
    bind=True,
    max_retries=2,
    queue="default",
    time_limit=1800,
)
def prune_retention_task(self: Any) -> dict[str, Any]:
    """Prune expired raw, processed, feed, and risk event records."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            result = await prune_expired_records(session, policy=RetentionPolicy())
            return {
                "status": "success",
                "raw_deleted": result.raw_deleted,
                "processed_deleted": result.processed_deleted,
                "feed_deleted": result.feed_deleted,
                "risk_events_deleted": result.risk_events_deleted,
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)


@app.task(
    name="worker.tasks.health_check_task",
    bind=True,
    queue="default",
    time_limit=30,
)
def health_check_task(self: Any) -> dict[str, str]:
    """Health check task for worker liveness."""
    return {
        "status": "healthy",
        "worker": str(self.request.hostname),
        "timestamp": datetime.utcnow().isoformat(),
    }


__all__ = [
    "health_check_task",
    "enrich_articles_task",
    "generate_risk_events_task",
    "normalize_articles_task",
    "personalize_feeds_task",
    "prune_retention_task",
    "process_article_for_signals",
    "retrieve_news_task",
]
