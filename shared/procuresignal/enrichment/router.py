"""Pure routing decisions for cost-aware enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from procuresignal.enrichment.policy import EnrichmentPolicy


class EnrichmentRoute(str, Enum):
    """Available enrichment processing paths."""

    CACHED = "cached"
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """A stable route, reason, and the supplied deterministic confidence."""

    route: EnrichmentRoute
    reason: str
    confidence: float


class EnrichmentRouter:
    """Choose an enrichment path without I/O or budget mutation."""

    def decide(
        self,
        *,
        cache_hit: bool,
        relevance: float,
        confidence: float,
        policy: EnrichmentPolicy,
        budget_available: bool,
    ) -> RouteDecision:
        """Apply the routing table in strict priority order."""
        _validate_score("relevance", relevance)
        _validate_score("confidence", confidence)
        if cache_hit:
            return RouteDecision(EnrichmentRoute.CACHED, "compatible_cache_hit", confidence)
        if relevance < policy.min_relevance:
            return RouteDecision(EnrichmentRoute.SKIPPED, "below_relevance_threshold", confidence)
        if confidence >= policy.min_deterministic_confidence:
            return RouteDecision(EnrichmentRoute.DETERMINISTIC, "deterministic_confident", confidence)
        if budget_available:
            return RouteDecision(EnrichmentRoute.LLM, "ambiguous_relevant", confidence)
        return RouteDecision(EnrichmentRoute.DEFERRED, "llm_budget_exhausted", confidence)


def _validate_score(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
