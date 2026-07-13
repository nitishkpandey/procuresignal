import pytest
from procuresignal.enrichment.policy import EnrichmentPolicy
from procuresignal.enrichment.router import EnrichmentRoute, EnrichmentRouter


@pytest.mark.parametrize(
    ("cache_hit", "relevance", "confidence", "budget", "expected", "reason"),
    [
        (True, 0.1, 0.1, False, "cached", "compatible_cache_hit"),
        (False, 0.34, 0.99, True, "skipped", "below_relevance_threshold"),
        (False, 0.35, 0.72, True, "deterministic", "deterministic_confident"),
        (False, 0.90, 0.71, True, "llm", "ambiguous_relevant"),
        (False, 0.90, 0.71, False, "deferred", "llm_budget_exhausted"),
    ],
)
def test_complete_routing_decision_table(
    cache_hit: bool,
    relevance: float,
    confidence: float,
    budget: bool,
    expected: str,
    reason: str,
) -> None:
    decision = EnrichmentRouter().decide(
        cache_hit=cache_hit,
        relevance=relevance,
        confidence=confidence,
        policy=EnrichmentPolicy(),
        budget_available=budget,
    )

    assert decision.route is EnrichmentRoute(expected)
    assert decision.reason == reason
    assert decision.confidence == confidence


@pytest.mark.parametrize("name", ["relevance", "confidence"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_router_rejects_out_of_bounds_scores(name: str, value: float) -> None:
    values = {"relevance": 0.5, "confidence": 0.5, name: value}

    with pytest.raises(ValueError, match=name):
        EnrichmentRouter().decide(
            cache_hit=False,
            policy=EnrichmentPolicy(),
            budget_available=True,
            **values,
        )
