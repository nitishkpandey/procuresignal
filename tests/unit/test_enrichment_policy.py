"""Tests for cost policy, hard budgets, and content fingerprints."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest
from procuresignal.enrichment import EnrichmentBudget, EnrichmentPolicy, content_fingerprint
from procuresignal.retrieval import RawArticle


@pytest.fixture
def raw_article() -> RawArticle:
    return RawArticle(
        provider="rss",
        provider_article_id="article-1",
        query_group="supplier_risk",
        title="Acme opens a factory",
        description="Production expands in Berlin.",
        content_snippet="The new site opens next month.",
        article_url="https://example.com/article-1",
        canonical_url=None,
        source_name="Example News",
        source_url="https://example.com",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        language="en",
    )


def test_policy_defaults_are_balanced() -> None:
    policy = EnrichmentPolicy.from_env({})
    assert policy.min_relevance == 0.35
    assert policy.min_deterministic_confidence == 0.72
    assert policy.min_fallback_confidence == 0.50
    assert policy.max_llm_calls == 5
    assert policy.max_llm_tokens == 6000
    assert policy.summary_max_chars == 420
    assert policy.policy_version == "cost-v1"
    assert policy.taxonomy_version == "signals-v1"


def test_policy_reads_all_environment_overrides() -> None:
    policy = EnrichmentPolicy.from_env(
        {
            "ENRICH_MIN_RELEVANCE": "0.4",
            "ENRICH_MIN_DETERMINISTIC_CONFIDENCE": "0.8",
            "ENRICH_MIN_FALLBACK_CONFIDENCE": "0.6",
            "ENRICH_MAX_LLM_CALLS": "7",
            "ENRICH_MAX_LLM_TOKENS": "8000",
            "ENRICH_SUMMARY_MAX_CHARS": "500",
            "ENRICH_POLICY_VERSION": "cost-v2",
            "ENRICH_TAXONOMY_VERSION": "signals-v2",
        }
    )
    assert policy == EnrichmentPolicy(0.4, 0.8, 7, 8000, 500, "cost-v2", "signals-v2", 0.6)


@pytest.mark.parametrize(
    "name",
    [
        "ENRICH_MIN_RELEVANCE",
        "ENRICH_MIN_DETERMINISTIC_CONFIDENCE",
        "ENRICH_MIN_FALLBACK_CONFIDENCE",
    ],
)
@pytest.mark.parametrize("value", ["-0.01", "1.01"])
def test_policy_rejects_floats_outside_unit_interval(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        EnrichmentPolicy.from_env({name: value})


def test_policy_rejects_fallback_above_deterministic_threshold() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        EnrichmentPolicy(min_deterministic_confidence=0.4, min_fallback_confidence=0.5)


@pytest.mark.parametrize(
    "name", ["ENRICH_MAX_LLM_CALLS", "ENRICH_MAX_LLM_TOKENS", "ENRICH_SUMMARY_MAX_CHARS"]
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_policy_rejects_non_positive_caps(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        EnrichmentPolicy.from_env({name: value})


@pytest.mark.parametrize(
    "name", ["ENRICH_MAX_LLM_CALLS", "ENRICH_MAX_LLM_TOKENS", "ENRICH_SUMMARY_MAX_CHARS"]
)
@pytest.mark.parametrize("value", ["1.5", "many"])
def test_policy_rejects_non_integer_environment_values(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        EnrichmentPolicy.from_env({name: value})


def test_policy_is_immutable() -> None:
    policy = EnrichmentPolicy.from_env({})
    with pytest.raises(FrozenInstanceError):
        policy.max_llm_calls = 9  # type: ignore[misc]


def test_budget_enforces_call_and_token_caps() -> None:
    budget = EnrichmentBudget(max_calls=1, max_tokens=100)
    assert budget.reserve(80) is True
    assert budget.reserve(1) is False
    budget.record_usage(65)
    assert budget.calls_reserved == 1
    assert budget.tokens_reserved == 80
    assert budget.tokens_used == 65


def test_budget_does_not_partially_reserve_when_token_cap_is_exceeded() -> None:
    budget = EnrichmentBudget(max_calls=2, max_tokens=100)
    assert budget.reserve(101) is False
    assert budget.calls_reserved == 0
    assert budget.tokens_reserved == 0


@pytest.mark.parametrize("max_calls,max_tokens", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_budget_rejects_non_positive_caps(max_calls: int, max_tokens: int) -> None:
    with pytest.raises(ValueError):
        EnrichmentBudget(max_calls=max_calls, max_tokens=max_tokens)


@pytest.mark.parametrize("tokens", [-1, 0])
def test_budget_rejects_non_positive_reservations(tokens: int) -> None:
    with pytest.raises(ValueError):
        EnrichmentBudget(max_calls=1, max_tokens=10).reserve(tokens)


def test_budget_rejects_negative_actual_usage() -> None:
    with pytest.raises(ValueError):
        EnrichmentBudget(max_calls=1, max_tokens=10).record_usage(-1)


def test_fingerprint_is_content_and_version_stable(raw_article: RawArticle) -> None:
    first = content_fingerprint(
        raw_article, policy_version="cost-v1", taxonomy_version="signals-v1"
    )
    second = content_fingerprint(
        raw_article, policy_version="cost-v1", taxonomy_version="signals-v1"
    )
    changed = content_fingerprint(
        raw_article, policy_version="cost-v2", taxonomy_version="signals-v1"
    )
    assert first == second
    assert first != changed
    assert len(first) == 64


def test_fingerprint_normalizes_unicode_case_and_whitespace(raw_article: RawArticle) -> None:
    normalized = RawArticle(**{**raw_article.__dict__, "title": "acme opens a factory"})
    variant = RawArticle(**{**raw_article.__dict__, "title": "  ACME\t opens  a FACTORY  "})
    composed = RawArticle(**{**raw_article.__dict__, "description": "Café"})
    decomposed = RawArticle(**{**raw_article.__dict__, "description": "CAFE\u0301"})
    kwargs = {"policy_version": "cost-v1", "taxonomy_version": "signals-v1"}
    assert content_fingerprint(normalized, **kwargs) == content_fingerprint(variant, **kwargs)
    assert content_fingerprint(composed, **kwargs) == content_fingerprint(decomposed, **kwargs)


def test_fingerprint_is_language_sensitive(raw_article: RawArticle) -> None:
    german = RawArticle(**{**raw_article.__dict__, "language": "de"})
    kwargs = {"policy_version": "cost-v1", "taxonomy_version": "signals-v1"}
    assert content_fingerprint(raw_article, **kwargs) != content_fingerprint(german, **kwargs)
