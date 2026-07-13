"""Tests for personalization engine."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from procuresignal.models import NewsArticleProcessed
from procuresignal.personalization import PreferenceMatcher
from procuresignal.signals.taxonomy import expand_signal_terms


def test_expand_signal_terms_preserves_none_stringification() -> None:
    """Optional matcher values retain the historical stringification behavior."""

    assert "none" in expand_signal_terms([None])


@dataclass
class PreferenceStub:
    """Preference stub for matcher tests."""

    user_id: str
    preferred_categories: list[str]
    preferred_suppliers: list[str]
    preferred_regions: list[str]
    preferred_signals: list[str]
    excluded_topics: list[str]
    excluded_suppliers: list[str]
    excluded_regions: list[str]
    excluded_signals: list[str]


def test_category_match_hit():
    """Test category matching when preferences match."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["automotive", "manufacturing"],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("automotive", pref)

    assert score == 1.0


def test_category_match_miss():
    """Test category matching when preferences don't match."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["automotive"],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=["general"],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("general", pref)

    assert score == 0.0


def test_category_match_no_preference():
    """Test category matching with no preferences."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("automotive", pref)

    assert score == 0.5  # Neutral


def test_category_alias_match_hit():
    """Common user wording should map to the article taxonomy."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["automobiles"],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("automotive", pref)

    assert score == 1.0


def test_procurement_category_alias_match_hit():
    """Procurement wording should map into richer category buckets."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["critical minerals"],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("metals_mining", pref)

    assert score == 1.0


def test_supplier_match_hit():
    """Test supplier matching when preferences match."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=["Bosch", "Siemens"],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_supplier_match(["Bosch"], pref)

    assert score > 0.5


def test_supplier_match_multiple():
    """Test supplier matching with multiple matches."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=["Bosch", "Siemens", "Volkswagen"],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_supplier_match(["Bosch", "Siemens"], pref)

    assert score > 0.7


def test_region_match_hit():
    """Test region matching when preferences match."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=["Germany", "Poland"],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_region_match(["Germany"], pref)

    assert score > 0.5


def test_signal_match_priority():
    """Test signal matching with priority signal."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=["bankruptcy", "strike"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    score = PreferenceMatcher.calculate_signal_match(["tariff"], "bankruptcy", pref)

    assert score == 1.0


def test_match_score_calculation():
    """Test overall match score calculation."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["automotive"],
        preferred_suppliers=["Bosch"],
        preferred_regions=["Germany"],
        preferred_signals=["tariff"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )

    # Create a mock article
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Test",
        summary="Test summary",
        top_level_category="automotive",
        signal_tags=["tariff"],
        priority_signal=None,
        detected_suppliers=["Bosch"],
        detected_regions=["Germany"],
        detected_categories=["automotive"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    score = asyncio.run(PreferenceMatcher.score_article(article, pref))

    assert score.overall_score > 0.7


def test_focused_preferences_reject_unrelated_signal_only_article():
    """A matching signal alone should not flood the feed when focus preferences exist."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["technology"],
        preferred_suppliers=["openai", "anthropic"],
        preferred_regions=["usa", "india"],
        preferred_signals=["m_and_a"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Critical metals deal update",
        summary="A mining company announced a transaction update.",
        top_level_category="energy",
        signal_tags=["m_and_a"],
        priority_signal="m_and_a",
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["energy"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is False


def test_focused_preferences_include_category_alias():
    """A category alias should include matching articles instead of emptying the feed."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["automobiles"],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Auto supplier expands in Germany",
        summary="A vehicle parts supplier opened a new plant.",
        top_level_category="automotive",
        signal_tags=["expansion"],
        priority_signal="expansion",
        detected_suppliers=[],
        detected_regions=["Germany"],
        detected_categories=["automotive"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True


def test_excluded_category_alias_wins():
    """Excluded aliases should still suppress matching articles."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=["cars"],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Auto supplier expands in Germany",
        summary="A vehicle parts supplier opened a new plant.",
        top_level_category="automotive",
        signal_tags=["expansion"],
        priority_signal="expansion",
        detected_suppliers=[],
        detected_regions=["Germany"],
        detected_categories=["automotive"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is False


def test_focused_preferences_include_supplier_match():
    """A supplier match is enough to include an article even if the category is imperfect."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["technology"],
        preferred_suppliers=["openai", "anthropic"],
        preferred_regions=["usa", "india"],
        preferred_signals=["m_and_a"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="OpenAI signs new infrastructure deal",
        summary="OpenAI expanded its data center supply chain.",
        top_level_category="energy",
        signal_tags=["m_and_a"],
        priority_signal="m_and_a",
        detected_suppliers=["OpenAI"],
        detected_regions=[],
        detected_categories=["technology"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True


def test_focused_preferences_include_supplier_mentioned_in_title():
    """Supplier names in title/summary count when entity extraction is missing."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=["technology"],
        preferred_suppliers=["openai", "anthropic"],
        preferred_regions=["usa", "india"],
        preferred_signals=["regulatory"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="OpenAI discusses government stake",
        summary="The AI vendor is negotiating with federal agencies.",
        top_level_category="general",
        signal_tags=["regulatory"],
        priority_signal="regulatory",
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["general"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True


def test_region_preference_matches_region_mentioned_in_text():
    """Locations like China should match even when entity extraction missed metadata."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=["China"],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Chinese manufacturers face new export checks",
        summary="Procurement teams are reviewing component sourcing in China.",
        top_level_category="manufacturing",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["manufacturing"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True
    score = asyncio.run(PreferenceMatcher.score_article(article, pref))
    assert score.region_match > 0.5


def test_region_exclusion_matches_region_mentioned_in_text():
    """Text-based region extraction should also honor explicit exclusions."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=["China"],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="China shipping lanes face disruption",
        summary="Importers are reviewing Asia routing.",
        top_level_category="logistics",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["logistics"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is False


def test_misc_signal_preference_matches_supply_chain_language():
    """Misc risk signals should accept natural procurement wording."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=["supply chain"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Manufacturers warn of renewed supply chain disruption",
        summary="Logistics delays are affecting component deliveries across Europe.",
        top_level_category="logistics",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["logistics"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True
    score = asyncio.run(PreferenceMatcher.score_article(article, pref))
    assert score.signal_match > 0.5


def test_misc_signal_preference_matches_middle_east_risk_language():
    """Risk signals can represent regional risk topics such as the Middle East."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=["middle east"],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="LNG tanker attack threatens Qatar exports through Hormuz",
        summary="Energy buyers are reviewing Middle East shipping risk after the incident.",
        top_level_category="energy",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["energy"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is True
    score = asyncio.run(PreferenceMatcher.score_article(article, pref))
    assert score.signal_match > 0.5


def test_misc_signal_exclusion_matches_text_language():
    """Natural-language risk exclusions should suppress text matches."""
    pref = PreferenceStub(
        user_id="user1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_topics=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=["war"],
    )
    article = NewsArticleProcessed(
        raw_article_id=1,
        normalized_title="Trade war raises supplier pricing risk",
        summary="Importers are reviewing contracts after tariff threats escalated.",
        top_level_category="regulatory",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["regulatory"],
        signal_score=0.8,
        processing_status="completed",
        llm_model="test",
        language="en",
        processed_at=datetime.utcnow(),
    )

    assert PreferenceMatcher.should_include_article(article, pref) is False
