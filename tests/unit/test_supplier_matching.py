"""Matching watched suppliers by identity rather than spelling."""

import pytest
from procuresignal.models import NewsArticleProcessed, UserNewsPreference
from procuresignal.personalization.matcher import PreferenceMatcher


def _article(**overrides) -> NewsArticleProcessed:
    defaults = dict(
        raw_article_id=1,
        normalized_title="Tariff pressure on European suppliers",
        summary="Procurement teams expect delays.",
        top_level_category="logistics",
        signal_tags=[],
        priority_signal=None,
        detected_regions=[],
        detected_suppliers=[],
        detected_categories=["logistics"],
    )
    defaults.update(overrides)
    return NewsArticleProcessed(**defaults)


def _preference(**overrides) -> UserNewsPreference:
    defaults = dict(
        user_id="u1",
        preferred_categories=[],
        preferred_suppliers=[],
        preferred_regions=[],
        preferred_signals=[],
        excluded_categories=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
        excluded_topics=[],
        preferred_supplier_ids=[],
        excluded_supplier_ids=[],
    )
    defaults.update(overrides)
    return UserNewsPreference(**defaults)


# --- the false positives measured on main before this phase ----------------------


@pytest.mark.parametrize(
    ("watched", "text"),
    [
        ("ABB", "Local cabbage prices rose sharply across the region."),
        ("3M", "The Q3 margin fell after the 3m-long delay in shipping."),
        ("Aptiv", "Captive insurance costs increased for logistics firms."),
        ("SAP", "The company will resap the flooring next quarter."),
    ],
)
def test_short_names_no_longer_match_inside_words(watched: str, text: str) -> None:
    assert PreferenceMatcher.text_mentions_supplier(text, watched) is False


@pytest.mark.parametrize(
    ("watched", "text"),
    [
        ("ABB", "ABB won the substation contract."),
        ("Bosch", "Suppliers including Bosch, Continental and ZF were named."),
        ("Siemens", "A statement from Siemens confirmed the delay."),
        ("Saint-Gobain", "Saint-Gobain reported lower volumes."),
    ],
)
def test_genuine_mentions_still_match(watched: str, text: str) -> None:
    assert PreferenceMatcher.text_mentions_supplier(text, watched) is True


def test_matching_ignores_case_and_surrounding_punctuation() -> None:
    assert PreferenceMatcher.text_mentions_supplier("Shares in BOSCH fell.", "bosch") is True
    assert PreferenceMatcher.text_mentions_supplier("(Bosch) confirmed it.", "Bosch") is True


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_supplier_never_matches(blank: str) -> None:
    assert PreferenceMatcher.text_mentions_supplier("anything at all", blank) is False


@pytest.mark.parametrize("short", ["3M", "AB", "X"])
def test_very_short_names_are_never_matched_in_free_text(short: str) -> None:
    """They are registry-only, and this is a deliberate trade.

    "3M" appears inside "3m-long delay", and the alternative — refusing to treat a
    trailing hyphen as a word boundary — would break legitimate forms such as
    "Bosch-owned". A name this short is matched exactly through the registry instead,
    which is also why the registry declines to derive aliases below this length.
    """
    assert PreferenceMatcher.text_mentions_supplier(f"{short} raised prices.", short) is False


def test_a_short_name_still_matches_through_identity() -> None:
    """Registering 3M is how a user watching it actually receives its news."""
    article = _article(detected_suppliers=["3M Co"])
    preference = _preference(preferred_suppliers=["3M"], preferred_supplier_ids=["sup-3m"])

    assert PreferenceMatcher.should_include_article(
        article, preference, article_supplier_ids={"sup-3m"}
    )


# --- identity matching -----------------------------------------------------------


def test_spelling_differences_no_longer_miss() -> None:
    """Article says "Siemens AG", user watches "Siemens": both resolve to one supplier."""
    article = _article(detected_suppliers=["Siemens AG"])
    preference = _preference(preferred_suppliers=["Siemens"], preferred_supplier_ids=["sup-1"])

    assert PreferenceMatcher.should_include_article(
        article, preference, article_supplier_ids={"sup-1"}
    )


def test_a_spinoff_does_not_satisfy_a_watch_on_its_parent() -> None:
    article = _article(detected_suppliers=["Siemens Energy AG"])
    preference = _preference(preferred_suppliers=["Siemens AG"], preferred_supplier_ids=["sup-1"])

    assert not PreferenceMatcher.should_include_article(
        article, preference, article_supplier_ids={"sup-2"}
    )


def test_unregistered_supplier_still_matches_on_text() -> None:
    """A user must not silently stop receiving news for a supplier nobody registered."""
    article = _article(detected_suppliers=["Obscure Parts Ltd"])
    preference = _preference(preferred_suppliers=["Obscure Parts Ltd"])

    assert PreferenceMatcher.should_include_article(article, preference, article_supplier_ids=set())


def test_identity_exclusion_beats_a_spelling_difference() -> None:
    """Excluding "Siemens" must also exclude an article that wrote "Siemens AG"."""
    article = _article(detected_suppliers=["Siemens AG"])
    preference = _preference(
        preferred_categories=["logistics"],
        excluded_suppliers=["Siemens"],
        excluded_supplier_ids=["sup-1"],
    )

    assert PreferenceMatcher.has_excluded_match(article, preference, article_supplier_ids={"sup-1"})


def test_exclusion_does_not_catch_a_different_entity() -> None:
    article = _article(detected_suppliers=["Siemens Energy AG"])
    preference = _preference(excluded_suppliers=["Siemens"], excluded_supplier_ids=["sup-1"])

    assert not PreferenceMatcher.has_excluded_match(
        article, preference, article_supplier_ids={"sup-2"}
    )


def test_scoring_rewards_an_identity_match() -> None:
    preference = _preference(preferred_suppliers=["Siemens"], preferred_supplier_ids=["sup-1"])

    matched = PreferenceMatcher.calculate_supplier_match(
        ["Siemens AG"], preference, article_supplier_ids={"sup-1"}
    )
    unmatched = PreferenceMatcher.calculate_supplier_match(
        ["Nobody Ltd"], preference, article_supplier_ids={"sup-9"}
    )

    assert matched > unmatched


def test_callers_that_pass_no_identity_still_work() -> None:
    """The parameter is optional, so existing call sites keep their behaviour."""
    article = _article(detected_suppliers=["Bosch"])
    preference = _preference(preferred_suppliers=["Bosch"])

    assert PreferenceMatcher.should_include_article(article, preference)
    assert PreferenceMatcher.calculate_supplier_match(["Bosch"], preference) > 0.5
