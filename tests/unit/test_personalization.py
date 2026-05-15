"""Tests for personalization engine."""

import asyncio
from datetime import datetime

from procuresignal.models import NewsArticleProcessed, UserNewsPreference
from procuresignal.personalization import (
    PreferenceMatcher,
)


def test_category_match_hit():
    """Test category matching when preferences match."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=["automotive", "manufacturing"],
        interested_suppliers=[],
        interested_regions=[],
        interested_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("automotive", pref)

    assert score == 1.0


def test_category_match_miss():
    """Test category matching when preferences don't match."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=["automotive"],
        interested_suppliers=[],
        interested_regions=[],
        interested_signals=[],
        excluded_categories=["general"],
    )

    score = PreferenceMatcher.calculate_category_match("general", pref)

    assert score == 0.0


def test_category_match_no_preference():
    """Test category matching with no preferences."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=[],
        interested_suppliers=[],
        interested_regions=[],
        interested_signals=[],
    )

    score = PreferenceMatcher.calculate_category_match("automotive", pref)

    assert score == 0.5  # Neutral


def test_supplier_match_hit():
    """Test supplier matching when preferences match."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=[],
        interested_suppliers=["Bosch", "Siemens"],
        interested_regions=[],
        interested_signals=[],
    )

    score = PreferenceMatcher.calculate_supplier_match(["Bosch"], pref)

    assert score > 0.5


def test_supplier_match_multiple():
    """Test supplier matching with multiple matches."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=[],
        interested_suppliers=["Bosch", "Siemens", "Volkswagen"],
        interested_regions=[],
        interested_signals=[],
    )

    score = PreferenceMatcher.calculate_supplier_match(["Bosch", "Siemens"], pref)

    assert score > 0.7


def test_region_match_hit():
    """Test region matching when preferences match."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=[],
        interested_suppliers=[],
        interested_regions=["Germany", "Poland"],
        interested_signals=[],
    )

    score = PreferenceMatcher.calculate_region_match(["Germany"], pref)

    assert score > 0.5


def test_signal_match_priority():
    """Test signal matching with priority signal."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=[],
        interested_suppliers=[],
        interested_regions=[],
        interested_signals=["bankruptcy", "strike"],
    )

    score = PreferenceMatcher.calculate_signal_match(["tariff"], "bankruptcy", pref)

    assert score == 1.0


def test_match_score_calculation():
    """Test overall match score calculation."""
    pref = UserNewsPreference(
        user_id="user1",
        interested_categories=["automotive"],
        interested_suppliers=["Bosch"],
        interested_regions=["Germany"],
        interested_signals=["tariff"],
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
