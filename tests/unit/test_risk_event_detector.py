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


def test_detector_merges_processed_and_text_extracted_locations() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Attack disrupts exports from Qatar",
            summary="An attack threatens shipments to Germany.",
            detected_regions=["Qatar"],
        ),
        _raw(
            title="Attack disrupts exports from Qatar",
            description="An attack threatens shipments to Germany.",
            content_snippet="Buyers are reviewing the conflict impact.",
        ),
    )

    assert len(events) == 1
    assert events[0].affected_locations == ["Qatar", "Germany"]


def test_detector_ignores_location_only_geopolitical_aliases() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Qatar investment supports regional growth",
            summary="The company announced a new business investment in Qatar.",
            detected_regions=["Qatar"],
            signal_tags=[],
            priority_signal=None,
        ),
        _raw(
            title="Qatar investment supports regional growth",
            description="The company announced a new business investment in Qatar.",
            content_snippet="The project is focused on commercial expansion and jobs.",
        ),
    )

    assert events == []


def test_detector_uses_existing_signal_tags() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="New import duty raises cost pressure",
            summary="Procurement teams are reviewing new customs duties.",
            signal_tags=["tariff"],
            priority_signal="tariff",
            detected_regions=["Germany"],
        ),
        _raw(
            title="New import duty raises cost pressure",
            description="Procurement teams are reviewing the updated customs rules.",
            content_snippet="Procurement teams are reviewing the updated customs rules.",
        ),
    )

    assert [event.risk_type for event in events] == ["tariff"]
    assert events[0].affected_locations == ["Germany"]
    assert events[0].confidence >= 0.75


def test_detector_uses_content_snippet_when_other_article_text_is_neutral() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Supplier update draws market attention",
            summary="Procurement teams are monitoring the supplier update.",
            signal_tags=[],
            priority_signal=None,
            detected_regions=[],
        ),
        _raw(
            title="Supplier update draws market attention",
            description="Procurement teams are monitoring the supplier update.",
            content_snippet="The supplier filed for bankruptcy after missing debt payments.",
        ),
    )

    assert [event.risk_type for event in events] == ["bankruptcy"]
    assert "bankruptcy" in events[0].evidence_snippet.lower()


def test_unrelated_signal_metadata_does_not_suppress_explicit_text_risk() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Supplier seeks court protection",
            summary="The company filed for bankruptcy after prolonged losses.",
            signal_tags=["supplier_risk"],
            priority_signal=None,
        ),
        _raw(
            title="Supplier seeks court protection",
            description="The company filed for bankruptcy after prolonged losses.",
            content_snippet="Creditors are reviewing the filing.",
        ),
    )

    assert [event.risk_type for event in events] == ["bankruptcy"]


def test_detector_returns_empty_list_for_non_procurement_article() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Markets move slightly after earnings",
            summary="Investors watched technology stocks during a quiet session.",
            signal_tags=[],
            priority_signal=None,
            detected_regions=[],
        ),
        _raw(
            title="Markets move slightly after earnings",
            description="A quiet session.",
            content_snippet="Investors watched technology stocks during a quiet session.",
        ),
    )

    assert events == []


def test_detector_ignores_broad_single_word_aliases() -> None:
    cases = [
        ("Company signs supplier deal", "The supplier deal expands commercial cooperation."),
        ("Quality leadership changes", "The company announced new quality leadership."),
        ("Euro sales rise", "Euro sales increased across the region."),
        ("Metals demand grows", "Metals demand is rising in automotive markets."),
        ("Company leaders strike a deal", "The leaders will strike a deal this week."),
        ("Conflict of interest policy updated", "The new conflict of interest policy applies."),
        ("Pricing attack gains attention", "A marketing attack won customer attention."),
    ]

    for title, summary in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_categories=[],
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events == []


def test_detector_ignores_generic_risk_nouns_without_a_risk_phrase() -> None:
    cases = [
        ("Compliance team expands", "The compliance team hired two analysts."),
        ("Legislation briefing published", "The legislation briefing summarizes current law."),
        ("Logistics team grows", "The logistics team opened a new office."),
        ("Customs training scheduled", "Customs training is available for new hires."),
        ("Commodity research released", "The commodity research covers market history."),
    ]

    for title, summary in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_categories=[],
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events == []


def test_detector_requires_context_for_ambiguous_metadata() -> None:
    cases = [
        (
            "Company leaders strike a deal",
            "The leaders will strike a deal this week.",
            "strike",
        ),
        (
            "Supplier deal expands cooperation",
            "The supplier deal expands commercial cooperation.",
            "m&a",
        ),
        (
            "Conflict of interest policy updated",
            "The policy describes internal conflict of interest rules.",
            "geopolitical",
        ),
    ]

    for title, summary, signal in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[signal],
                priority_signal=signal,
                detected_regions=[],
                detected_categories=[],
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events == []


def test_detector_does_not_treat_detected_entities_as_text_evidence() -> None:
    cases = [
        (
            "Company update draws market attention",
            "The company announced a routine commercial update.",
            "m&a",
            ["merger"],
            [],
        ),
        (
            "Supplier update draws market attention",
            "The supplier announced a routine commercial update.",
            "strike",
            ["port strike"],
            [],
        ),
        (
            "Regional update draws market attention",
            "The company announced a routine commercial update.",
            "geopolitical",
            ["geopolitical risk"],
            ["Qatar"],
        ),
    ]

    for title, summary, signal, categories, regions in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[signal],
                priority_signal=signal,
                detected_regions=regions,
                detected_categories=categories,
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events == []


def test_detector_keeps_conservative_risk_phrases() -> None:
    cases = [
        ("Acquisition announced", "The supplier announced an acquisition."),
        ("Quality issue triggers recall", "A quality issue led to a product recall."),
        ("FX risk rises", "Exchange rate volatility creates currency risk."),
        ("Raw material shortage", "A raw material shortage threatens production."),
        ("Port strike threatens deliveries", "A port strike is disrupting supplier shipments."),
        ("Tanker attack threatens exports", "A shipping attack threatens energy exports."),
    ]

    for title, summary in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_categories=[],
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events


def test_detector_keeps_strong_generic_noun_risk_phrases() -> None:
    cases = [
        ("Customs change raises duties", "A customs change increases import duties."),
        ("New regulation takes effect", "The new regulation creates a supplier mandate."),
        ("Port delay disrupts shipments", "A shipping delay is affecting deliveries."),
        ("Commodity price rises", "Raw material shortage threatens production."),
    ]

    for title, summary in cases:
        events = detect_risk_events(
            _processed(
                normalized_title=title,
                summary=summary,
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_categories=[],
            ),
            _raw(title=title, description=summary, content_snippet=summary),
        )

        assert events
