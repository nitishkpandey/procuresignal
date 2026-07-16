"""Bounded, durable orchestration for registry-backed retrieval."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import AsyncContextManager, Callable
from urllib.parse import urlsplit

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsRetrievalRun
from procuresignal.retrieval.audit import LEASE_DURATION, RetrievalAuditRepository
from procuresignal.retrieval.base import FetchFailureCode, NewsProvider
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.deduplication import deduplicate_within_run
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.persistence import ArticlePersistence
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.registry import AdapterType, SourceDefinition, SourceRegistry
from procuresignal.retrieval.security import URLSafetyPolicy


@dataclass(frozen=True, slots=True)
class SourceRetrievalResult:
    source_id: str
    status: str
    fetched: int = 0
    inserted: int = 0
    within_run_duplicates: int = 0
    database_duplicates: int = 0
    errors: int = 0
    failure_code: str | None = None
    response_bytes: int = 0
    latency_ms: int = 0
    circuit_state: str = "closed"
    next_poll_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetrievalRunResult:
    status: str
    run_id: int | None
    registry_version: str
    source_results: tuple[SourceRetrievalResult, ...] = ()
    articles_fetched: int = 0
    articles_inserted: int = 0
    duplicates: int = 0
    errors: int = 0
    within_run_duplicates: int = 0
    database_duplicates: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    response_bytes: int = 0
    latency_ms: int = 0
    circuit_state: dict[str, str] = field(default_factory=dict)
    next_poll_at: datetime | None = None


ProviderFactory = Callable[[SourceDefinition], NewsProvider]
SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        registry: SourceRegistry = SOURCE_REGISTRY,
        registry_version: str = REGISTRY_VERSION,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.registry_version = registry_version
        self.provider_factory = provider_factory
        self.owner = str(uuid.uuid4())
        self._global = asyncio.Semaphore(6)
        self._hosts: dict[str, asyncio.Semaphore] = {}

    async def _claim(self, run_key: str, now: datetime) -> tuple[NewsRetrievalRun, bool, str]:
        async with self.session_factory() as session:
            run = await session.scalar(
                select(NewsRetrievalRun).where(NewsRetrievalRun.run_key == run_key)
            )
            if run is None:
                run = NewsRetrievalRun(
                    run_key=run_key,
                    status="running",
                    registry_version=self.registry_version,
                    started_at=now,
                    lease_owner=self.owner,
                    lease_expires_at=now + LEASE_DURATION,
                    attempted_count=1,
                )
                session.add(run)
                try:
                    await session.commit()
                    return run, True, "running"
                except IntegrityError:
                    await session.rollback()
                    run = await session.scalar(
                        select(NewsRetrievalRun).where(NewsRetrievalRun.run_key == run_key)
                    )
                    assert run is not None
            if run.status == "completed":
                return run, False, "already_completed"
            result = await session.execute(
                update(NewsRetrievalRun)
                .where(
                    NewsRetrievalRun.id == run.id,
                    NewsRetrievalRun.status == "running",
                    or_(
                        NewsRetrievalRun.lease_expires_at.is_(None),
                        NewsRetrievalRun.lease_expires_at < now,
                    ),
                )
                .values(
                    lease_owner=self.owner,
                    lease_expires_at=now + LEASE_DURATION,
                    attempted_count=NewsRetrievalRun.attempted_count + 1,
                )
            )
            await session.commit()
            if getattr(result, "rowcount", 0) == 1:
                return run, True, "running"
            return run, False, "already_running"

    def _provider(
        self, definition: SourceDefinition, repo: RetrievalAuditRepository
    ) -> NewsProvider:
        if self.provider_factory is not None:
            return self.provider_factory(definition)
        if definition.adapter is not AdapterType.RSS:
            raise ValueError("unsupported_adapter")
        fetcher = SafeFetcher(policy=URLSafetyPolicy(), circuit_store=repo, owner=self.owner)
        provider = RSSProvider(definition, fetcher)
        provider.close = fetcher.aclose  # type: ignore[method-assign]
        return provider

    async def _source(self, run_id: int, definition: SourceDefinition) -> SourceRetrievalResult:
        host = urlsplit(definition.endpoint_url).hostname or ""
        host_semaphore = self._hosts.setdefault(host, asyncio.Semaphore(2))
        started = time.monotonic()
        now = datetime.utcnow()
        async with self.session_factory() as session:
            repo = RetrievalAuditRepository(session)
            if not await repo.claim_source(run_id, definition.source_id, self.owner, now):
                return SourceRetrievalResult(definition.source_id, "already_claimed")
            provider = self._provider(definition, repo)
            try:
                async with self._global, host_semaphore:
                    articles = await provider.fetch_articles([])
                deduped = deduplicate_within_run(articles)
                inserted, database_duplicates, errors = await ArticlePersistence.save_articles(
                    session, list(deduped.articles)
                )
                response_bytes = sum(
                    len(json.dumps(article.raw_payload_json or {}, default=str).encode())
                    for article in articles
                )
                await repo.complete_source(
                    run_id,
                    definition.source_id,
                    self.owner,
                    now=datetime.utcnow(),
                    fetched_count=len(articles),
                    accepted_count=len(deduped.articles),
                    inserted_count=inserted,
                    duplicate_count=database_duplicates + deduped.duplicates,
                    failed_count=errors,
                )
                return SourceRetrievalResult(
                    definition.source_id,
                    "completed",
                    len(articles),
                    inserted,
                    deduped.duplicates,
                    database_duplicates,
                    errors,
                    response_bytes=response_bytes,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    next_poll_at=now + timedelta(minutes=definition.poll_minutes),
                )
            except Exception as exc:
                code = (
                    FetchFailureCode.NETWORK_ERROR
                    if isinstance(exc, (TimeoutError, ConnectionError))
                    else FetchFailureCode.PARSER_ERROR
                )
                await repo.fail_source(
                    run_id, definition.source_id, self.owner, code, now=datetime.utcnow()
                )
                return SourceRetrievalResult(
                    definition.source_id,
                    "failed",
                    errors=1,
                    failure_code=code.value,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    next_poll_at=now + timedelta(minutes=definition.poll_minutes),
                )
            finally:
                await provider.close()

    async def run(self, run_key: str) -> RetrievalRunResult:
        started = time.monotonic()
        now = datetime.utcnow()
        run, acquired, status = await self._claim(run_key, now)
        if not acquired:
            return RetrievalRunResult(status, run.id, self.registry_version)
        results = tuple(
            await asyncio.gather(
                *(self._source(run.id, definition) for definition in self.registry.enabled())
            )
        )
        fetched = sum(item.fetched for item in results)
        inserted = sum(item.inserted for item in results)
        within = sum(item.within_run_duplicates for item in results)
        database = sum(item.database_duplicates for item in results)
        errors = sum(item.errors for item in results)
        reasons: dict[str, int] = {}
        for item in results:
            if item.failure_code:
                reasons[item.failure_code] = reasons.get(item.failure_code, 0) + 1
        async with self.session_factory() as session:
            await RetrievalAuditRepository(session).complete_run(
                run.id,
                self.owner,
                now=datetime.utcnow(),
                fetched_count=fetched,
                accepted_count=fetched - within,
                inserted_count=inserted,
                duplicate_count=within + database,
                failed_count=errors,
            )
        return RetrievalRunResult(
            "completed",
            run.id,
            self.registry_version,
            results,
            fetched,
            inserted,
            within + database,
            errors,
            within,
            database,
            reasons,
            sum(item.response_bytes for item in results),
            int((time.monotonic() - started) * 1000),
            {item.source_id: item.circuit_state for item in results},
            min((item.next_poll_at for item in results if item.next_poll_at), default=None),
        )
