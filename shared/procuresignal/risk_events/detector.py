"""Rule-based risk event detector."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from procuresignal.enrichment.entities import canonical_region_name, extract_regions_from_text
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.signals.taxonomy import (
    expand_signal_terms,
    normalize_signal_term,
    text_matches_signal_terms,
)

from .taxonomy import (
    RECOMMENDATIONS,
    RISK_TYPE_ORDER,
    SEVERITY_BY_RISK_TYPE,
    risk_terms_for,
)

_GEOPOLITICAL_TEXT_ALIASES = {
    "war",
    "armed conflict",
    "regional conflict",
    "geopolitical risk",
    "hostilities",
    "military action",
    "missile attack",
    "shipping attack",
    "attack threatens",
    "attack disrupts",
    "escalation of hostilities",
}
_GEOPOLITICAL_ACTION_TERMS = expand_signal_terms(_GEOPOLITICAL_TEXT_ALIASES)
_CONSERVATIVE_TEXT_ALIASES = {
    "geopolitical": _GEOPOLITICAL_TEXT_ALIASES,
    "regional_conflict": _GEOPOLITICAL_TEXT_ALIASES,
    "tariff": {
        "tariff increase",
        "tariff hike",
        "new tariff",
        "customs change",
        "customs duty increase",
        "duty increase",
        "import duty",
        "trade duty",
    },
    "regulatory": {
        "new regulation",
        "regulatory mandate",
        "compliance requirement",
        "legislation passed",
        "legislative requirement",
    },
    "quality": {"quality issue", "recall", "defect"},
    "m_and_a": {"m&a", "m_and_a", "merger", "acquisition", "takeover"},
    "strike": {
        "port strike",
        "labor strike",
        "labour strike",
        "union strike",
        "worker strike",
        "workers strike",
        "factory strike",
        "strike disruption",
        "labor dispute",
        "labour dispute",
        "walkout",
    },
    "currency": {"foreign exchange", "fx", "exchange rate", "currency risk"},
    "logistics": {
        "logistics disruption",
        "port delay",
        "shipping delay",
        "transport disruption",
        "shipping disruption",
    },
    "commodity": {"commodity price", "raw material shortage", "critical minerals", "energy price"},
}


@dataclass(frozen=True)
class RiskEventCandidate:
    risk_type: str
    severity: str
    confidence: float
    affected_suppliers: list[str]
    affected_locations: list[str]
    affected_categories: list[str]
    evidence_snippet: str
    recommendation: str


def detect_risk_events(
    processed: NewsArticleProcessed,
    raw: NewsArticleRaw | None = None,
) -> list[RiskEventCandidate]:
    """Detect procurement risk events from one processed article."""

    text = _article_text(processed, raw)
    signal_values = [processed.priority_signal, *(processed.signal_tags or [])]
    article_signal_terms = risk_terms_for(signal_values)
    events: list[RiskEventCandidate] = []

    for risk_type in RISK_TYPE_ORDER:
        terms = risk_terms_for([risk_type])
        text_terms = _text_terms_for(risk_type, terms)
        raw_metadata_match = bool(article_signal_terms & terms)
        text_match = (
            _text_matches_exact(text, text_terms)
            if risk_type in _CONSERVATIVE_TEXT_ALIASES
            else text_matches_signal_terms(text, text_terms)
        )
        metadata_match = (
            raw_metadata_match and text_match
            if risk_type in _CONSERVATIVE_TEXT_ALIASES
            else raw_metadata_match
        )
        if risk_type in {"geopolitical", "regional_conflict"} and not (
            article_signal_terms & _GEOPOLITICAL_ACTION_TERMS
            or text_matches_signal_terms(text, _GEOPOLITICAL_ACTION_TERMS)
        ):
            continue
        if not metadata_match and not text_match:
            continue

        confidence = _confidence(metadata_match, text_match, processed)
        if confidence < 0.55:
            continue

        events.append(
            RiskEventCandidate(
                risk_type=risk_type,
                severity=_severity(risk_type, text),
                confidence=confidence,
                affected_suppliers=_dedupe(processed.detected_suppliers or []),
                affected_locations=_locations(processed, text),
                affected_categories=_dedupe(
                    [processed.top_level_category, *(processed.detected_categories or [])]
                ),
                evidence_snippet=_evidence(text, text_terms),
                recommendation=RECOMMENDATIONS[risk_type],
            )
        )

    return _dedupe_events(events)


def _text_terms_for(risk_type: str, terms: set[str]) -> set[str]:
    aliases = _CONSERVATIVE_TEXT_ALIASES.get(risk_type)
    if aliases is None:
        return terms
    return {
        variant
        for alias in aliases
        for variant in (
            normalize_signal_term(alias),
            normalize_signal_term(alias).replace("_", " "),
        )
    }


def _text_matches_exact(text: str, terms: set[str]) -> bool:
    normalized_text = normalize_signal_term(text)
    return any(
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalize_signal_term(term))}(?![a-z0-9])",
            normalized_text,
        )
        for term in terms
    )


def _article_text(processed: NewsArticleProcessed, raw: NewsArticleRaw | None) -> str:
    parts = [
        processed.normalized_title,
        processed.summary,
        raw.title if raw else "",
        raw.description if raw else "",
        raw.content_snippet if raw else "",
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _confidence(metadata_match: bool, text_match: bool, processed: NewsArticleProcessed) -> float:
    score = 0.5
    if metadata_match:
        score += 0.25
    if text_match:
        score += 0.25
    if processed.priority_signal:
        score += 0.05
    if processed.detected_suppliers:
        score += 0.03
    if processed.detected_regions:
        score += 0.02
    return min(score, 0.95)


def _severity(risk_type: str, text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("bankruptcy", "missile", "shutdown", "embargo")):
        return "critical" if risk_type in {"bankruptcy", "geopolitical", "sanctions"} else "high"
    return SEVERITY_BY_RISK_TYPE[risk_type]


def _locations(processed: NewsArticleProcessed, text: str) -> list[str]:
    detected = [
        *(processed.detected_regions or []),
        *extract_regions_from_text(text),
    ]
    return _dedupe(canonical_region_name(value) for value in detected)


def _evidence(text: str, terms: set[str]) -> str:
    lowered = text.lower()
    match_positions = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
    if not match_positions:
        return text[:260].strip()
    center = min(match_positions)
    start = max(0, center - 90)
    end = min(len(text), center + 170)
    return text[start:end].strip()


def _dedupe(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _dedupe_events(events: list[RiskEventCandidate]) -> list[RiskEventCandidate]:
    by_type: dict[str, RiskEventCandidate] = {}
    for event in events:
        current = by_type.get(event.risk_type)
        if current is None or event.confidence > current.confidence:
            by_type[event.risk_type] = event

    geopolitical = [by_type.get(risk_type) for risk_type in ("geopolitical", "regional_conflict")]
    family_events = [event for event in geopolitical if event is not None]
    if len(family_events) > 1:
        strongest = max(
            family_events,
            key=lambda event: (event.confidence, -RISK_TYPE_ORDER.index(event.risk_type)),
        )
        for event in family_events:
            if event is not strongest:
                by_type.pop(event.risk_type, None)

    return [event for event in events if by_type.get(event.risk_type) is event]
