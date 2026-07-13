"""Configuration and hard in-process budgets for article enrichment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True, slots=True)
class EnrichmentPolicy:
    """Validated cost and quality policy for one enrichment run."""

    min_relevance: float = 0.35
    min_deterministic_confidence: float = 0.72
    max_llm_calls: int = 5
    max_llm_tokens: int = 6000
    summary_max_chars: int = 420
    policy_version: str = "cost-v1"
    taxonomy_version: str = "signals-v1"
    min_fallback_confidence: float = 0.50

    def __post_init__(self) -> None:
        for name in ("min_relevance", "min_deterministic_confidence", "min_fallback_confidence"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"{name} must be between 0 and 1")
        if self.min_fallback_confidence > self.min_deterministic_confidence:
            raise ValueError("min_fallback_confidence cannot exceed min_deterministic_confidence")
        for name in ("max_llm_calls", "max_llm_tokens", "summary_max_chars"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EnrichmentPolicy:
        """Build a validated policy from enrichment-specific environment values."""
        values = os.environ if environ is None else environ
        return cls(
            min_relevance=_read_float(values, "ENRICH_MIN_RELEVANCE", 0.35),
            min_deterministic_confidence=_read_float(
                values,
                "ENRICH_MIN_DETERMINISTIC_CONFIDENCE",
                0.72,
            ),
            max_llm_calls=_read_int(values, "ENRICH_MAX_LLM_CALLS", 5),
            max_llm_tokens=_read_int(values, "ENRICH_MAX_LLM_TOKENS", 6000),
            summary_max_chars=_read_int(values, "ENRICH_SUMMARY_MAX_CHARS", 420),
            policy_version=values.get("ENRICH_POLICY_VERSION", "cost-v1"),
            taxonomy_version=values.get("ENRICH_TAXONOMY_VERSION", "signals-v1"),
            min_fallback_confidence=_read_float(values, "ENRICH_MIN_FALLBACK_CONFIDENCE", 0.50),
        )


def _read_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error


def _read_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


@dataclass(frozen=True, slots=True)
class EnrichmentBudget:
    """Thread-safe reservation and usage accounting for a single process run."""

    max_calls: int
    max_tokens: int
    _calls_reserved: int = field(default=0, init=False, repr=False, compare=False)
    _tokens_reserved: int = field(default=0, init=False, repr=False, compare=False)
    _tokens_used: int = field(default=0, init=False, repr=False, compare=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in ("max_calls", "max_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def calls_reserved(self) -> int:
        with self._lock:
            return self._calls_reserved

    @property
    def tokens_reserved(self) -> int:
        with self._lock:
            return self._tokens_reserved

    @property
    def tokens_used(self) -> int:
        with self._lock:
            return self._tokens_used

    def reserve(self, estimated_tokens: int) -> bool:
        """Reserve one call and its estimated tokens if both caps allow it."""
        if (
            not isinstance(estimated_tokens, int)
            or isinstance(estimated_tokens, bool)
            or estimated_tokens <= 0
        ):
            raise ValueError("estimated_tokens must be a positive integer")
        with self._lock:
            if self._calls_reserved >= self.max_calls:
                return False
            if self._tokens_reserved + estimated_tokens > self.max_tokens:
                return False
            object.__setattr__(self, "_calls_reserved", self._calls_reserved + 1)
            object.__setattr__(self, "_tokens_reserved", self._tokens_reserved + estimated_tokens)
            return True

    def record_usage(self, actual_tokens: int) -> None:
        """Record non-negative actual usage without releasing a reservation."""
        if (
            not isinstance(actual_tokens, int)
            or isinstance(actual_tokens, bool)
            or actual_tokens < 0
        ):
            raise ValueError("actual_tokens must be a non-negative integer")
        with self._lock:
            object.__setattr__(self, "_tokens_used", self._tokens_used + actual_tokens)
