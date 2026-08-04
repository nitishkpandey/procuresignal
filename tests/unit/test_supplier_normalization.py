"""Tests for supplier name normalization."""

import pytest
from procuresignal.suppliers.normalization import (
    LEGAL_FORMS,
    MINIMUM_DERIVED_ALIAS_LENGTH,
    alias_forms,
    normalize,
    strip_legal_form,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Siemens AG", "siemens ag"),
        ("  SIEMENS   AG  ", "siemens ag"),
        ("Robert Bosch GmbH", "robert bosch gmbh"),
        ("O'Reilly Automotive, Inc.", "o reilly automotive inc"),
        ("Saint-Gobain S.A.", "saint gobain s a"),
        ("Thyssenkrupp\tAG\n", "thyssenkrupp ag"),
        ("3M Co", "3m co"),
    ],
)
def test_normalize_is_stable_across_case_spacing_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize("blank", ["", "   ", "...", None])
def test_normalize_handles_empty_input(blank) -> None:
    assert normalize(blank) == ""


def test_normalize_keeps_the_legal_form() -> None:
    """It produces the canonical key, where the legal form is what keeps entities apart."""
    assert normalize("Siemens AG") != normalize("Siemens Energy AG")
    assert "ag" in normalize("Siemens AG").split()


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        ("siemens ag", "siemens"),
        ("robert bosch gmbh", "robert bosch"),
        ("basf se", "basf"),
        ("apple inc", "apple"),
        ("nexans", "nexans"),
        ("volvo ab", "volvo"),
    ],
)
def test_strip_removes_one_trailing_legal_form(normalized: str, expected: str) -> None:
    assert strip_legal_form(normalized) == expected


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        # Punctuated forms survive normalization as separate tokens and must still strip.
        ("saint gobain s a", "saint gobain"),
        ("fiat s p a", "fiat"),
        ("philips n v", "philips"),
    ],
)
def test_strip_handles_legal_forms_split_by_punctuation(normalized: str, expected: str) -> None:
    assert strip_legal_form(normalized) == expected


def test_strip_leaves_leading_matches_alone() -> None:
    """ "AG Barr" is a company name, not a legal form followed by a word."""
    assert strip_legal_form("ag barr") == "ag barr"
    assert strip_legal_form("co operative group holdings") == "co operative group holdings"


def test_strip_removes_only_one_form() -> None:
    """Repeated stripping would eat a name down to nothing useful."""
    assert strip_legal_form("company co") == "company"


def test_strip_never_returns_empty() -> None:
    """A name that is nothing but a legal form must survive as itself."""
    assert strip_legal_form("ag") == "ag"
    assert strip_legal_form("s a") == "s a"


@pytest.mark.parametrize("descriptor", ["group", "holding", "holdings"])
def test_corporate_descriptors_are_not_legal_forms(descriptor: str) -> None:
    """Stripping these merges genuinely different entities.

    "Volkswagen Group" and "Volkswagen AG" are not the same registrant, and collapsing
    both to "volkswagen" would make one of them unregisterable.
    """
    assert descriptor not in LEGAL_FORMS
    assert strip_legal_form(f"volkswagen {descriptor}") == f"volkswagen {descriptor}"


def test_alias_forms_include_canonical_and_stripped() -> None:
    assert alias_forms("Siemens AG") == ["siemens ag", "siemens"]


def test_alias_forms_deduplicate_when_there_is_no_legal_form() -> None:
    assert alias_forms("Nexans") == ["nexans"]


def test_alias_forms_are_empty_for_empty_input() -> None:
    assert alias_forms("") == []


@pytest.mark.parametrize("name", ["3M Co", "AB Ltd"])
def test_derived_aliases_are_not_dangerously_short(name: str) -> None:
    """An automatically derived two-character alias is a guess not worth making.

    An operator can still add one deliberately through the registry; this only governs
    what is generated without anyone asking.
    """
    assert all(len(form) >= MINIMUM_DERIVED_ALIAS_LENGTH for form in alias_forms(name))


def test_a_spinoff_and_its_parent_derive_different_aliases() -> None:
    """The whole point: these must not collide into one entity."""
    assert set(alias_forms("Siemens AG")) & set(alias_forms("Siemens Energy AG")) == set()


def test_alias_forms_do_not_repeat_themselves() -> None:
    forms = alias_forms("Bosch")
    assert len(forms) == len(set(forms))


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        # "Co., Ltd." is the standard pairing across much of East Asia, and these are
        # core procurement suppliers.
        ("foxconn technology co ltd", "foxconn technology"),
        ("samsung electronics co ltd", "samsung electronics"),
        ("shanghai pudong machinery co ltd", "shanghai pudong machinery"),
    ],
)
def test_strip_handles_stacked_legal_forms(normalized: str, expected: str) -> None:
    assert strip_legal_form(normalized) == expected


def test_stripping_stops_before_erasing_the_name() -> None:
    """A name made only of legal forms must survive rather than reduce to nothing."""
    assert strip_legal_form("company co") == "company"
    assert strip_legal_form("holding ag") == "holding"
    assert strip_legal_form("ltd") == "ltd"
