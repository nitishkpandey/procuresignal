"""Tests for personalization engine."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from procuresignal.models import NewsArticleProcessed
from procuresignal.personalization import PreferenceMatcher


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
