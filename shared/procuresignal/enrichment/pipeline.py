"""Cost-aware enrichment cascade and route accounting."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.enrichment.cache import EnrichmentCache
from procuresignal.enrichment.deterministic import DeterministicEnricher
from procuresignal.enrichment.enricher import ArticleEnricher
from procuresignal.enrichment.fingerprint import content_fingerprint
from procuresignal.enrichment.openai_client import OpenAILLMClient
from procuresignal.enrichment.output_parser import EnrichmentOutput
from procuresignal.enrichment.policy import EnrichmentBudget, EnrichmentPolicy
from procuresignal.enrichment.router import EnrichmentRoute, EnrichmentRouter
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.retrieval import RawArticle


@dataclass(slots=True)
class EnrichmentMetrics:
    cached: int = 0
    deterministic: int = 0
    llm: int = 0
    skipped: int = 0
    deferred: int = 0
    failed: int = 0
    cache_misses: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    avoided_llm_calls: int = 0


@dataclass(slots=True)
class EnrichmentRunResult:
    saved: int
    metrics: EnrichmentMetrics
    already_processed: int = 0

    def __iter__(self) -> Iterator[int]:
        """Preserve the former worker tuple contract during rollout."""
        yield self.saved
        yield self.metrics.skipped + self.already_processed
        yield self.metrics.failed


class EnrichmentPipeline:
    """Orchestrate the full enrichment process."""

    # Batch size for LLM calls
    BATCH_SIZE = 10

    def __init__(
        self,
        llm_client: Optional[OpenAILLMClient] = None,
        *,
        policy: EnrichmentPolicy | None = None,
        router: EnrichmentRouter | None = None,
        deterministic_enricher: DeterministicEnricher | None = None,
        cache: EnrichmentCache | None = None,
    ):
        """Initialize pipeline.

        Args:
            llm_client: OpenAI client instance
        """
        self.policy = policy or EnrichmentPolicy.from_env()
        self.router = router or EnrichmentRouter()
        self.deterministic_enricher = deterministic_enricher or DeterministicEnricher()
        self.cache = cache or EnrichmentCache()
        self.llm_client = llm_client
        self.enricher = ArticleEnricher(llm_client) if llm_client is not None else None

    async def process_raw_articles(
        self,
        session: AsyncSession,
        raw_articles: list[NewsArticleRaw],
    ) -> EnrichmentRunResult:
        """Process raw articles through enrichment pipeline.

        Args:
            session: Database session
            raw_articles: List of raw articles from database

        Returns:
            (enriched_count, skipped_count, error_count)
        """
        metrics = EnrichmentMetrics()
        saved = 0
        budget = EnrichmentBudget(self.policy.max_llm_calls, self.policy.max_llm_tokens)

        # Check for already-processed articles
        processed_raw_ids = set()
        existing = await session.execute(select(NewsArticleProcessed.raw_article_id))
        for row in existing:
            processed_raw_ids.add(row[0])

        # Filter to unprocessed articles
        articles_to_process = [a for a in raw_articles if a.id not in processed_raw_ids]
        already_processed = len(raw_articles) - len(articles_to_process)
        try:
            for raw in articles_to_process:
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
                    article,
                    policy_version=self.policy.policy_version,
                    taxonomy_version=self.policy.taxonomy_version,
                )
                cached = await self.cache.get(
                    session,
                    fingerprint=fingerprint,
                    policy_version=self.policy.policy_version,
                    taxonomy_version=self.policy.taxonomy_version,
                )
                if cached is None:
                    metrics.cache_misses += 1
                analysis = self.deterministic_enricher.analyze(
                    article, summary_max_chars=self.policy.summary_max_chars
                )
                estimate = self._estimated_tokens(article)
                budget_available = (
                    budget.calls_reserved < budget.max_calls
                    and budget.tokens_reserved + estimate <= budget.max_tokens
                    and self.enricher is not None
                )
                decision = self.router.decide(
                    cache_hit=cached is not None,
                    relevance=analysis.relevance,
                    confidence=analysis.confidence,
                    policy=self.policy,
                    budget_available=budget_available,
                )
                output: EnrichmentOutput | None = None
                method = decision.route.value
                llm_used = False
                if decision.route is EnrichmentRoute.CACHED:
                    output = cached.output if cached else None
                elif decision.route is EnrichmentRoute.DETERMINISTIC:
                    output = analysis.output
                elif decision.route is EnrichmentRoute.LLM:
                    if not budget.reserve(estimate):
                        decision = self.router.decide(
                            cache_hit=False,
                            relevance=analysis.relevance,
                            confidence=analysis.confidence,
                            policy=self.policy,
                            budget_available=False,
                        )
                        method = decision.route.value
                    else:
                        metrics.llm_calls += 1
                        before = self._client_tokens()
                        output = (
                            await self.enricher.generate_output(article) if self.enricher else None
                        )
                        used = max(0, self._client_tokens() - before)
                        budget.record_usage(used)
                        metrics.llm_tokens += used
                        if output is not None:
                            llm_used = True
                        elif analysis.confidence >= self.policy.min_deterministic_confidence:
                            output = analysis.output
                            method = EnrichmentRoute.DETERMINISTIC.value
                            decision = type(decision)(
                                EnrichmentRoute.DETERMINISTIC,
                                "llm_failure_deterministic_fallback",
                                analysis.confidence,
                            )
                        else:
                            method = "failed"
                if output is None:
                    route = method if method == "failed" else decision.route.value
                    setattr(metrics, route, getattr(metrics, route) + 1)
                    continue
                processed = self._processed(
                    raw.id,
                    article,
                    output,
                    method,
                    decision.reason,
                    fingerprint,
                    analysis.confidence,
                    llm_used,
                )
                session.add(processed)
                saved += 1
                setattr(metrics, method, getattr(metrics, method) + 1)
                if method in {"deterministic", "llm"}:
                    await self.cache.put(
                        session,
                        fingerprint=fingerprint,
                        policy_version=self.policy.policy_version,
                        taxonomy_version=self.policy.taxonomy_version,
                        output=output,
                        original_method=method,
                    )
            metrics.avoided_llm_calls = metrics.cached + metrics.deterministic + metrics.skipped
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return EnrichmentRunResult(
            saved=saved, metrics=metrics, already_processed=already_processed
        )

    def _processed(
        self,
        raw_id: int,
        article: RawArticle,
        output: EnrichmentOutput,
        method: str,
        reason: str,
        fingerprint: str,
        confidence: float,
        llm_used: bool,
    ) -> NewsArticleProcessed:
        return NewsArticleProcessed(
            raw_article_id=raw_id,
            normalized_title=article.title,
            summary=output.summary,
            top_level_category=output.category,
            signal_tags=output.signal_tags,
            priority_signal=output.priority_signal,
            detected_regions=output.detected_regions,
            detected_suppliers=output.detected_suppliers,
            detected_categories=output.detected_categories or [output.category],
            signal_score=0.0,
            processing_status="completed",
            llm_model=(f"openai/{self.llm_client.model}" if llm_used and self.llm_client else None),
            language=article.language,
            processed_at=datetime.utcnow(),
            enrichment_method=method,
            enrichment_reason=reason,
            enrichment_policy_version=self.policy.policy_version,
            content_fingerprint=fingerprint,
            deterministic_confidence=confidence,
            llm_used=llm_used,
        )

    @staticmethod
    def _estimated_tokens(article: RawArticle) -> int:
        chars = (
            len(article.title) + len(article.description or "") + len(article.content_snippet or "")
        )
        return max(1, chars // 4 + 400)

    def _client_tokens(self) -> int:
        return int(getattr(self.llm_client, "total_tokens_used", 0))

    def get_stats(self) -> dict:
        """Get enrichment statistics."""
        if self.llm_client is None:
            return {"total_tokens": 0, "total_calls": 0, "avg_tokens_per_call": 0, "model": None}
        return {**self.llm_client.get_usage_stats(), "model": f"openai/{self.llm_client.model}"}
