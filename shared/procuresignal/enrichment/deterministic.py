"""Pure, rule-based article analysis for cost-aware enrichment."""

from __future__ import annotations

from dataclasses import dataclass

from procuresignal.enrichment.entities import (
    extract_regions_from_text,
    extract_suppliers_from_text,
)
from procuresignal.enrichment.output_parser import EnrichmentOutput
from procuresignal.personalization.categories import CANONICAL_CATEGORIES, canonical_category
from procuresignal.retrieval import RawArticle
from procuresignal.retrieval.queries import QUERY_GROUPS
from procuresignal.signals.classifier import SignalClassifier
from procuresignal.signals.taxonomy import PRIORITY_SIGNAL_TAGS, canonical_signal_tags

# Relevance measures independent evidence that an article matters to procurement.
RELEVANCE_SIGNAL_WEIGHT = 0.45
RELEVANCE_QUERY_GROUP_WEIGHT = 0.25
RELEVANCE_ENTITY_WEIGHT = 0.20
RELEVANCE_CATEGORY_WEIGHT = 0.10

# Confidence measures the strength and completeness of deterministic evidence.
CONFIDENCE_SIGNAL_WEIGHT = 0.45
CONFIDENCE_ENTITY_WEIGHT = 0.20
CONFIDENCE_CATEGORY_WEIGHT = 0.20
CONFIDENCE_TEXT_COMPLETENESS_WEIGHT = 0.15


@dataclass(frozen=True, slots=True)
class DeterministicAnalysis:
    """Structured deterministic output and bounded decision scores."""

    output: EnrichmentOutput
    relevance: float
    confidence: float


class DeterministicEnricher:
    """Analyze an article without I/O or model calls."""

    def __init__(self, classifier: SignalClassifier | None = None) -> None:
        self._classifier = classifier or SignalClassifier()

    def analyze(self, article: RawArticle, *, summary_max_chars: int) -> DeterministicAnalysis:
        """Return repeatable enrichment using canonical classifiers and extractors."""
        if isinstance(summary_max_chars, bool) or summary_max_chars < 10:
            raise ValueError("summary_max_chars must be an integer of at least 10")

        parts = [article.title, article.description or "", article.content_snippet or ""]
        text = " ".join(part for part in parts if part)
        signals = self._classifier.classify(text, article.title)
        signal_tags = canonical_signal_tags(signal.signal_type.value for signal in signals)
        suppliers = extract_suppliers_from_text(text)
        regions = extract_regions_from_text(text)
        category, category_evidence = _infer_category(article, text)
        entity_evidence = min(1.0, (len(suppliers) + len(regions)) / 2)
        query_evidence = float(article.query_group in QUERY_GROUPS)
        signal_evidence = float(bool(signal_tags))
        text_completeness = sum(bool(part.strip()) for part in parts) / len(parts)
        signal_confidence = max((signal.confidence for signal in signals), default=0.0)

        relevance = _bounded(
            RELEVANCE_SIGNAL_WEIGHT * signal_evidence
            + RELEVANCE_QUERY_GROUP_WEIGHT * query_evidence
            + RELEVANCE_ENTITY_WEIGHT * entity_evidence
            + RELEVANCE_CATEGORY_WEIGHT * category_evidence
        )
        confidence = _bounded(
            CONFIDENCE_SIGNAL_WEIGHT * signal_confidence
            + CONFIDENCE_ENTITY_WEIGHT * entity_evidence
            + CONFIDENCE_CATEGORY_WEIGHT * category_evidence
            + CONFIDENCE_TEXT_COMPLETENESS_WEIGHT * text_completeness
        )
        priority_signal = next(
            (tag for tag in signal_tags if tag in PRIORITY_SIGNAL_TAGS),
            None,
        )
        output = EnrichmentOutput(
            summary=_summary(article, summary_max_chars),
            category=category,
            signal_tags=signal_tags,
            priority_signal=priority_signal,
            detected_suppliers=suppliers,
            detected_regions=regions,
            detected_categories=[category],
        )
        return DeterministicAnalysis(output=output, relevance=relevance, confidence=confidence)


def _infer_category(article: RawArticle, text: str) -> tuple[str, float]:
    for candidate in (article.query_group, text, article.source_name):
        category = canonical_category(candidate)
        if category in CANONICAL_CATEGORIES and category != "general":
            return category, 1.0
    return "general", 0.0


def _summary(article: RawArticle, max_chars: int) -> str:
    source = article.description or article.content_snippet or article.title
    normalized = " ".join(source.split())
    if len(normalized) <= max_chars:
        return normalized
    prefix = normalized[: max_chars - 1].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return f"{prefix}…"


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)
