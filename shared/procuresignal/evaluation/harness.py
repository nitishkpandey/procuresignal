"""Run a labelled query set against a retriever and report how it did.

The harness is deliberately ignorant of how retrieval works: it takes a callable that
turns a query into a list of article ids. That is what lets the same twelve labels score
lexical-only retrieval, hybrid retrieval, and whatever replaces them, on the same scale.

Queries whose correct answer is *no results* are scored explicitly rather than through the
ordinary metrics. Precision over an empty judgement set is zero however the system
behaves, which would punish the correct answer exactly as hard as the wrong one.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.evaluation.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw

PRECISION_K = 5
RECALL_K = 10
NDCG_K = 10

SearchFn = Callable[..., Awaitable[Sequence[int]]]


@dataclass(frozen=True)
class GoldenCase:
    query: str
    language: str
    relevant: list[int]
    why: str = ""

    @property
    def expects_nothing(self) -> bool:
        return not self.relevant


@dataclass(frozen=True)
class CaseResult:
    query: str
    language: str
    expects_nothing: bool
    retrieved: list[int]
    precision_at_5: float
    recall_at_10: float
    reciprocal_rank: float
    ndcg_at_10: float


@dataclass(frozen=True)
class EvaluationReport:
    mean_precision_at_5: float
    mean_recall_at_10: float
    mrr: float
    ndcg_at_10: float
    per_case: list[CaseResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_precision_at_5": round(self.mean_precision_at_5, 4),
            "mean_recall_at_10": round(self.mean_recall_at_10, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_10": round(self.ndcg_at_10, 4),
        }


def load_golden_set(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The corpus and the raw cases, still keyed by fixture id."""

    document = json.loads(path.read_text())
    return document["corpus"], document["cases"]


async def load_corpus(session: AsyncSession, corpus: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Insert the fixture corpus and return fixture id -> processed article id.

    Timestamps are staggered by minutes rather than shared, so that the recency tiebreak
    in retrieval is deterministic and an evaluation run is reproducible.
    """

    now = datetime.utcnow()
    mapping: dict[str, int] = {}

    for index, article in enumerate(corpus):
        when = now - timedelta(minutes=index)
        raw = NewsArticleRaw(
            provider="golden",
            query_group="golden",
            ingest_hash=f"golden-{article['id']}",
            title=article["title"],
            description=article["summary"],
            content_snippet=article["summary"],
            article_url=f"https://example.invalid/{article['id']}",
            source_name="Golden Fixture",
            published_at=when,
            language=article["language"],
            ingested_at=when,
        )
        session.add(raw)
        await session.flush()

        processed = NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=article["title"],
            summary=article["summary"],
            top_level_category="logistics",
            signal_score=0.5,
            processing_status="completed",
            language=article["language"],
            processed_at=when,
        )
        session.add(processed)
        await session.flush()
        mapping[article["id"]] = processed.id

    await session.commit()
    return mapping


def resolve_cases(cases: Sequence[dict[str, Any]], mapping: dict[str, int]) -> list[GoldenCase]:
    """Turn fixture ids into database ids, failing loudly on a label that names nothing.

    A typo in a label would otherwise silently make a relevant document unfindable and
    show up as a retrieval regression, which is the most confusing possible failure.
    """

    resolved = []
    for case in cases:
        try:
            relevant = [mapping[identifier] for identifier in case["relevant"]]
        except KeyError as missing:
            raise ValueError(
                f"case {case['query']!r} labels {missing} which is not in the corpus"
            ) from None
        resolved.append(
            GoldenCase(
                query=case["query"],
                language=case.get("language", "en"),
                relevant=relevant,
                why=case.get("why", ""),
            )
        )
    return resolved


def _score(case: GoldenCase, retrieved: Sequence[int]) -> CaseResult:
    if case.expects_nothing:
        # Scored as a single right-or-wrong judgement. Running the ordinary metrics here
        # would score the correct answer — an empty list — identically to returning the
        # entire corpus, since both have zero relevant results in them.
        correct = 1.0 if not retrieved else 0.0
        return CaseResult(
            query=case.query,
            language=case.language,
            expects_nothing=True,
            retrieved=list(retrieved),
            precision_at_5=correct,
            recall_at_10=correct,
            reciprocal_rank=correct,
            ndcg_at_10=correct,
        )

    return CaseResult(
        query=case.query,
        language=case.language,
        expects_nothing=False,
        retrieved=list(retrieved),
        precision_at_5=precision_at_k(retrieved, case.relevant, PRECISION_K),
        recall_at_10=recall_at_k(retrieved, case.relevant, RECALL_K),
        reciprocal_rank=reciprocal_rank(retrieved, case.relevant),
        ndcg_at_10=ndcg_at_k(retrieved, case.relevant, NDCG_K),
    )


async def run_evaluation(
    session: AsyncSession,
    *,
    cases: Sequence[GoldenCase],
    search_fn: SearchFn,
) -> EvaluationReport:
    """Score every case and average. Deterministic for a deterministic retriever."""

    results = [
        _score(case, await search_fn(session=session, query=case.query, language=case.language))
        for case in cases
    ]
    if not results:
        return EvaluationReport(0.0, 0.0, 0.0, 0.0, [])

    count = len(results)
    return EvaluationReport(
        mean_precision_at_5=sum(result.precision_at_5 for result in results) / count,
        mean_recall_at_10=sum(result.recall_at_10 for result in results) / count,
        # Computed from the same per-case numbers rather than recomputed from the raw
        # lists, so the headline figure and the per-case table can never disagree.
        mrr=sum(result.reciprocal_rank for result in results) / count,
        ndcg_at_10=sum(result.ndcg_at_10 for result in results) / count,
        per_case=results,
    )


__all__ = [
    "CaseResult",
    "EvaluationReport",
    "GoldenCase",
    "load_corpus",
    "load_golden_set",
    "mean_reciprocal_rank",
    "resolve_cases",
    "run_evaluation",
]
