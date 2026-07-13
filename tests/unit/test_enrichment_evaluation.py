"""Fixed offline quality and call-avoidance gate for deterministic enrichment."""

import json
from datetime import datetime
from pathlib import Path

from procuresignal.enrichment import (
    DeterministicEnricher,
    EnrichmentBudget,
    EnrichmentPolicy,
    EnrichmentRoute,
    EnrichmentRouter,
)
from procuresignal.retrieval import RawArticle

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "enrichment_evaluation.json"
DIMENSIONS = ("suppliers", "regions", "categories", "signals")


def _set_recall(actual: set[str], expected: set[str]) -> float:
    """Return exact set recall, treating an empty baseline as fully covered."""
    return 1.0 if not expected else len(actual & expected) / len(expected)


def _coverage(records, outputs, dimension: str) -> float:
    recalls = []
    output_field = {
        "suppliers": "detected_suppliers",
        "regions": "detected_regions",
        "categories": "detected_categories",
        "signals": "signal_tags",
    }[dimension]
    for record, output in zip(records, outputs, strict=True):
        expected = set(record["baseline"][dimension])
        recalls.append(_set_recall(set(getattr(output, output_field)), expected))
    return sum(recalls) / len(recalls)


def test_fixed_fixture_meets_cost_and_extraction_quality_gates() -> None:
    records = json.loads(FIXTURE_PATH.read_text())
    assert len(records) >= 20
    policy = EnrichmentPolicy.from_env({})
    budget = EnrichmentBudget(max_calls=5, max_tokens=6000)
    analyzer = DeterministicEnricher()
    router = EnrichmentRouter()
    accepted = []
    outputs = []
    avoided_calls = 0

    for index, record in enumerate(records):
        item = record["article"]
        article = RawArticle(
            provider=item["provider"],
            provider_article_id=str(index),
            query_group=item["query_group"],
            title=item["title"],
            description=item.get("description"),
            content_snippet=item.get("content_snippet"),
            article_url=f"https://example.test/{index}",
            canonical_url=None,
            source_name=item["source_name"],
            source_url=None,
            published_at=datetime(2026, 7, 1),
            language=item["language"],
        )
        analysis = analyzer.analyze(article, summary_max_chars=policy.summary_max_chars)
        expected_relevant = record["expected_relevance"] == "accepted"
        assert (analysis.relevance >= policy.min_relevance) is expected_relevant, record["id"]
        if not expected_relevant:
            continue
        estimate = 500
        budget_available = (
            budget.calls_reserved < budget.max_calls
            and budget.tokens_reserved + estimate <= budget.max_tokens
        )
        decision = router.decide(
            cache_hit=record.get("cache_hit", False),
            relevance=analysis.relevance,
            confidence=analysis.confidence,
            policy=policy,
            budget_available=budget_available,
        )
        if decision.route is EnrichmentRoute.LLM:
            assert budget.reserve(estimate)
        else:
            avoided_calls += 1
        accepted.append(record)
        outputs.append(analysis.output)

    avoidance_rate = avoided_calls / len(accepted)
    assert 0.70 <= avoidance_rate <= 0.85
    for dimension in DIMENSIONS:
        deterministic_coverage = _coverage(accepted, outputs, dimension)
        baseline_coverage = 1.0
        assert deterministic_coverage >= baseline_coverage - 0.05, (
            dimension,
            deterministic_coverage,
        )
