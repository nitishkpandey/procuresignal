"""Bounded, durable orchestration for registry-backed retrieval."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import AsyncContextManager, Callable
from urllib.parse import urlsplit

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsRetrievalRun
from procuresignal.retrieval.audit import LEASE_DURATION, RetrievalAuditRepository
from procuresignal.retrieval.base import (
    FetchFailureCode,
    NewsProvider,
    RetrievalFetchError,
)
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.deduplication import deduplicate_within_run
from procuresignal.retrieval.fetching import SafeFetcher
from procuresignal.retrieval.persistence import ArticlePersistence
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

    @property
    def llm_calls(self) -> int:
        """Retrieval is deterministic and never enters an enrichment/LLM path."""
        return 0

    @property
    def sources_succeeded(self) -> int:
        """Count sources that completed their isolated retrieval outcome."""
        return sum(item.status == "completed" for item in self.source_results)

    @property
    def sources_failed(self) -> int:
        """Count sources that failed without aborting the retrieval run."""
        return sum(item.status == "failed" for item in self.source_results)


ProviderFactory = Callable[[SourceDefinition], NewsProvider]
SessionFactory = Callable[[], AsyncContextManager[AsyncSession]]

NEWSAPI_QUERIES = (
    "procurement supply chain",
    "supplier risk",
    "tariff changes",
    "logistics disruption",
    "regulatory compliance",
    "European business procurement",
)
GDELT_QUERY_GROUPS = (
    "supplier_risk",
    "logistics_disruption",
    "tariff_changes",
    "regulatory",
    "europe_business",
)


def configured_registry(base: SourceRegistry = SOURCE_REGISTRY) -> SourceRegistry:
    """Apply explicit source toggles and add opt-in legacy providers."""
    additions: list[SourceDefinition] = []
    if os.getenv("NEWSAPI_KEY"):
        additions.append(
            SourceDefinition(
                source_id="newsapi",
                display_name="NewsAPI",
                homepage_url="https://newsapi.org/",
                endpoint_url=f"{NewsAPIProvider.BASE_URL}/everything",
                adapter=AdapterType.NEWSAPI,
                source_class=SourceClass.ESTABLISHED_MEDIA,
                domains=frozenset(
                    {
                        ProcurementDomain.REGULATION,
                        ProcurementDomain.LOGISTICS,
                        ProcurementDomain.SUPPLIER_RISK,
                        ProcurementDomain.EUROPE_BUSINESS,
                    }
                ),
                countries=("eu",),
                languages=("en",),
                poll_minutes=360,
                item_limit=100,
                expected_content_types=("application/json",),
                allowed_hosts=("newsapi.org",),
                trust_seed=0.65,
                license_note="Configured NewsAPI account; retain publisher attribution.",
            )
        )
    if os.getenv("GDELT_ENABLED", "false").lower() == "true":
        additions.append(
            SourceDefinition(
                source_id="gdelt",
                display_name="GDELT",
                homepage_url="https://www.gdeltproject.org/",
                endpoint_url=GDELTProvider.BASE_URL,
                adapter=AdapterType.GDELT,
                source_class=SourceClass.ESTABLISHED_MEDIA,
                domains=frozenset(
                    {
                        ProcurementDomain.REGULATION,
                        ProcurementDomain.LOGISTICS,
                        ProcurementDomain.SUPPLIER_RISK,
                        ProcurementDomain.EUROPE_BUSINESS,
                    }
                ),
                countries=("us",),
                languages=("en",),
                poll_minutes=360,
                item_limit=100,
                expected_content_types=("application/json",),
                allowed_hosts=("api.gdeltproject.org",),
                trust_seed=0.65,
                license_note="GDELT public API metadata with original publisher links.",
            )
        )
    configured: list[SourceDefinition] = []
    for source in (*base.sources, *additions):
        variable = f"SOURCE_{source.source_id.upper()}_ENABLED"
        raw_override = os.getenv(variable)
        if raw_override is None:
            configured.append(source)
            continue
        normalized = raw_override.strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"{variable} must be true or false")
        configured.append(replace(source, enabled_by_default=normalized == "true"))
    return SourceRegistry(tuple(configured))


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        registry: SourceRegistry = SOURCE_REGISTRY,
        registry_version: str = REGISTRY_VERSION,
        provider_factory: ProviderFactory | None = None,
        owner: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.registry_version = registry_version
        self.provider_factory = provider_factory
        self.owner = owner or str(uuid.uuid4())
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
            if run.status == "running" and run.lease_owner == self.owner:
                await session.execute(
                    update(NewsRetrievalRun)
                    .where(
                        NewsRetrievalRun.id == run.id,
                        NewsRetrievalRun.status == "running",
                        NewsRetrievalRun.lease_owner == self.owner,
                    )
                    .values(
                        lease_expires_at=now + LEASE_DURATION,
                        attempted_count=NewsRetrievalRun.attempted_count + 1,
                    )
                )
                await session.commit()
                return run, True, "running"
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
        if definition.adapter is AdapterType.RSS:
            fetcher = SafeFetcher(
                policy=URLSafetyPolicy(), circuit_store=repo, owner=self.owner, defer_success=True
            )
            provider = RSSProvider(definition, fetcher, registry_version=self.registry_version)
            provider.close = fetcher.aclose  # type: ignore[method-assign]
            return provider
        if definition.adapter is AdapterType.NEWSAPI:
            fetcher = SafeFetcher(
                policy=URLSafetyPolicy(), circuit_store=repo, owner=self.owner, defer_success=True
            )
            return NewsAPIProvider(source=definition, fetcher=fetcher)
        if definition.adapter is AdapterType.GDELT:
            fetcher = SafeFetcher(
                policy=URLSafetyPolicy(), circuit_store=repo, owner=self.owner, defer_success=True
            )
            return GDELTProvider(source=definition, fetcher=fetcher)
        raise ValueError("unsupported_adapter")

    @staticmethod
    def _queries(definition: SourceDefinition) -> list[str]:
        if definition.adapter is AdapterType.NEWSAPI:
            return list(NEWSAPI_QUERIES)
        if definition.adapter is AdapterType.GDELT:
            return list(GDELT_QUERY_GROUPS)
        return []

    async def _source(self, run_id: int, definition: SourceDefinition) -> SourceRetrievalResult:
        host = urlsplit(definition.endpoint_url).hostname or ""
        host_semaphore = self._hosts.setdefault(host, asyncio.Semaphore(2))
        started = time.monotonic()
        now = datetime.utcnow()
        async with self.session_factory() as session:
            repo = RetrievalAuditRepository(session)
            if not await repo.claim_source(run_id, definition.source_id, self.owner, now):
                return SourceRetrievalResult(definition.source_id, "already_claimed")
            provider: NewsProvider | None = None
            try:
                provider = self._provider(definition, repo)
                async with self._global, host_semaphore:
                    articles = await provider.fetch_articles(self._queries(definition))
                retrieved_at = datetime.utcnow()
                for article in articles:
                    article.source_id = article.source_id or definition.source_id
                    article.source_class = article.source_class or definition.source_class.value
                    article.source_domains = article.source_domains or tuple(
                        sorted(domain.value for domain in definition.domains)
                    )
                    article.source_countries = article.source_countries or definition.countries
                    article.registry_version = article.registry_version or self.registry_version
                    article.retrieved_at = article.retrieved_at or retrieved_at
                deduped = deduplicate_within_run(articles)
                if not await repo.fence_run(run_id, self.owner, datetime.utcnow()):
                    await session.rollback()
                    return SourceRetrievalResult(
                        definition.source_id,
                        "lease_lost",
                        errors=1,
                        failure_code="lease_lost",
                    )
                inserted, database_duplicates, errors = await ArticlePersistence.save_articles(
                    session, list(deduped.articles), commit=False
                )
                response_bytes = int(getattr(provider, "last_response_bytes", 0))
                completed = await repo.complete_source(
                    run_id,
                    definition.source_id,
                    self.owner,
                    now=datetime.utcnow(),
                    fetched_count=len(articles),
                    accepted_count=len(deduped.articles),
                    inserted_count=inserted,
                    duplicate_count=database_duplicates + deduped.duplicates,
                    failed_count=errors,
                    commit=False,
                )
                if not completed:
                    await session.rollback()
                    return SourceRetrievalResult(
                        definition.source_id,
                        "lease_lost",
                        errors=1,
                        failure_code="lease_lost",
                    )
                await session.commit()
                await repo.record_circuit_success(definition.source_id, self.owner)
                circuit_state = await repo.circuit_state(definition.source_id, datetime.utcnow())
                return SourceRetrievalResult(
                    definition.source_id,
                    "completed",
                    len(articles),
                    inserted,
                    deduped.duplicates,
                    database_duplicates,
                    errors,
                    response_bytes=response_bytes,
                    circuit_state=circuit_state,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    next_poll_at=now + timedelta(minutes=definition.poll_minutes),
                )
            except Exception as exc:
                code = (
                    exc.result.failure_code
                    if isinstance(exc, RetrievalFetchError)
                    else (
                        FetchFailureCode.NETWORK_ERROR
                        if isinstance(exc, (TimeoutError, ConnectionError))
                        else FetchFailureCode.PARSER_ERROR
                    )
                )
                code = code or FetchFailureCode.NETWORK_ERROR
                if code is FetchFailureCode.PARSER_ERROR:
                    await repo.record_circuit_failure(definition.source_id, datetime.utcnow())
                await repo.fail_source(
                    run_id, definition.source_id, self.owner, code, now=datetime.utcnow()
                )
                return SourceRetrievalResult(
                    definition.source_id,
                    "failed",
                    errors=1,
                    failure_code=code.value,
                    response_bytes=(
                        exc.result.response_bytes if isinstance(exc, RetrievalFetchError) else 0
                    ),
                    circuit_state=await repo.circuit_state(definition.source_id, datetime.utcnow()),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    next_poll_at=now + timedelta(minutes=definition.poll_minutes),
                )
            finally:
                if provider is not None:
                    try:
                        await provider.close()
                    except Exception:
                        pass

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
        if any(item.status == "lease_lost" for item in results):
            return RetrievalRunResult(
                "lease_lost",
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
            )
        async with self.session_factory() as session:
            completed = await RetrievalAuditRepository(session).complete_run(
                run.id,
                self.owner,
                now=datetime.utcnow(),
                fetched_count=fetched,
                accepted_count=fetched - within,
                inserted_count=inserted,
                duplicate_count=within + database,
                failed_count=errors,
            )
        if not completed:
            return RetrievalRunResult(
                "lease_lost",
                run.id,
                self.registry_version,
                results,
                fetched,
                inserted,
                within + database,
                errors + 1,
                within,
                database,
                {**reasons, "lease_lost": 1},
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
