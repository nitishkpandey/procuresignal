"""Tests for deterministic risk event detection."""

from datetime import datetime

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.risk_events.detector import detect_risk_events
from procuresignal.risk_events.taxonomy import normalize_risk_type, risk_terms_for


def _raw(**overrides) -> NewsArticleRaw:
    values = {
        "provider": "rss",
        "provider_article_id": "raw-1",
        "query_group": "supplier_risk",
        "ingest_hash": "raw-hash-1",
        "title": "LNG tanker attack threatens Qatar exports through Hormuz",
        "description": "Energy buyers are reviewing Middle East shipping risk.",
        "content_snippet": "The attack may disrupt supply chains in the Gulf.",
        "article_url": "https://example.com/risk",
        "source_name": "Reuters",
        "published_at": datetime.utcnow(),
        "ingested_at": datetime.utcnow(),
    }
    values.update(overrides)
    return NewsArticleRaw(**values)


def _processed(**overrides) -> NewsArticleProcessed:
    values = {
        "id": 77,
        "raw_article_id": 1,
        "normalized_title": "LNG tanker attack threatens Qatar exports through Hormuz",
        "summary": "Energy buyers are reviewing Middle East shipping risk after an attack.",
        "top_level_category": "energy",
        "signal_tags": [],
        "priority_signal": None,
        "detected_regions": [],
        "detected_suppliers": [],
        "detected_categories": ["energy"],
        "signal_score": 0.8,
        "processing_status": "completed",
        "llm_model": "openai/test",
        "language": "en",
        "processed_at": datetime.utcnow(),
    }
    values.update(overrides)
    return NewsArticleProcessed(**values)


def test_aliases_map_natural_terms_to_procurement_risks() -> None:
    assert normalize_risk_type("war") == "geopolitical"
    assert normalize_risk_type("middle east") == "regional_conflict"
    assert normalize_risk_type("supply chain") == "supply_disruption"
    assert "red sea" in risk_terms_for(["war"])


def test_detector_creates_geopolitical_event_with_evidence() -> None:
    events = detect_risk_events(_processed(), _raw())

    assert len(events) == 1
    event = events[0]
    assert event.risk_type in {"geopolitical", "regional_conflict"}
    assert event.severity in {"high", "critical"}
    assert event.confidence >= 0.7
    assert "Qatar" in event.affected_locations
    assert "energy" in event.affected_categories
    assert "attack" in event.evidence_snippet.lower()
    assert "Review supplier exposure" in event.recommendation


def test_detector_uses_existing_signal_tags() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="New import duty raises cost pressure",
            summary="Procurement teams are reviewing new customs duties.",
            signal_tags=["tariff"],
            priority_signal="tariff",
            detected_regions=["Germany"],
        ),
        _raw(title="New import duty raises cost pressure"),
    )

    assert [event.risk_type for event in events] == ["tariff"]
    assert events[0].affected_locations == ["Germany"]
    assert events[0].confidence >= 0.75


def test_detector_returns_empty_list_for_non_procurement_article() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Markets move slightly after earnings",
            summary="Investors watched technology stocks during a quiet session.",
            signal_tags=[],
            priority_signal=None,
            detected_regions=[],
        ),
        _raw(title="Markets move slightly after earnings", description="A quiet session."),
    )

    assert events == []
