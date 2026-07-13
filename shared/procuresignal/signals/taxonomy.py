"""Signal vocabulary and natural-language aliases."""

from __future__ import annotations

import re
from collections.abc import Iterable

VALID_SIGNAL_TAGS = frozenset(
    {
        "bankruptcy",
        "capacity_change",
        "executive_change",
        "expansion",
        "labor_dispute",
        "m_and_a",
        "natural_disaster",
        "port_strike",
        "price_change",
        "quality_issue",
        "regulatory",
        "sanctions",
        "strike",
        "supplier_risk",
        "supply_disruption",
        "tariff",
    }
)

CANONICAL_SIGNAL_TAG_ORDER = (
    "bankruptcy",
    "m_and_a",
    "tariff",
    "sanctions",
    "strike",
    "port_strike",
    "labor_dispute",
    "supply_disruption",
    "supplier_risk",
    "quality_issue",
    "regulatory",
    "natural_disaster",
    "price_change",
    "capacity_change",
    "executive_change",
    "expansion",
)

PRIORITY_SIGNAL_TAGS = frozenset(
    {
        "bankruptcy",
        "m_and_a",
        "port_strike",
        "quality_issue",
        "sanctions",
        "strike",
        "supply_disruption",
        "tariff",
    }
)

SIGNAL_ALIAS_GROUPS = (
    frozenset(
        {
            "bankruptcy",
            "chapter 11",
            "insolvency",
            "liquidation",
            "receivership",
        }
    ),
    frozenset(
        {
            "m&a",
            "m_and_a",
            "acquisition",
            "deal",
            "merger",
            "merger and acquisition",
            "takeover",
        }
    ),
    frozenset(
        {
            "tariff",
            "tariffs",
            "customs",
            "duties",
            "export restriction",
            "import duty",
            "trade barrier",
            "trade war",
        }
    ),
    frozenset(
        {
            "sanction",
            "sanctions",
            "embargo",
            "export control",
            "restricted party",
            "trade restriction",
        }
    ),
    frozenset(
        {
            "strike",
            "labor_dispute",
            "labour dispute",
            "labor dispute",
            "industrial action",
            "port strike",
            "port_strike",
            "walkout",
            "work stoppage",
        }
    ),
    frozenset(
        {
            "supply chain",
            "supply_chain",
            "supply disruption",
            "supply_disruption",
            "supply shortage",
            "component shortage",
            "facility closure",
            "logistics delay",
            "logistics delays",
            "logistics disruption",
            "port closure",
            "production halt",
            "shortage",
            "transport disruption",
        }
    ),
    frozenset(
        {
            "war",
            "attack",
            "conflict",
            "escalation",
            "geopolitical",
            "geopolitical risk",
            "hostilities",
            "military action",
            "missile",
            "shipping attack",
        }
    ),
    frozenset(
        {
            "middle east",
            "mideast",
            "bahrain",
            "gulf",
            "hormuz",
            "iran",
            "iraq",
            "israel",
            "jordan",
            "kuwait",
            "lebanon",
            "oman",
            "persian gulf",
            "qatar",
            "red sea",
            "saudi arabia",
            "strait of hormuz",
            "suez",
            "syria",
            "uae",
            "united arab emirates",
            "yemen",
        }
    ),
    frozenset(
        {
            "regulation",
            "regulatory",
            "compliance",
            "legislation",
            "mandate",
            "policy change",
        }
    ),
    frozenset(
        {
            "quality",
            "quality issue",
            "quality_issue",
            "recall",
            "defect",
        }
    ),
    frozenset(
        {
            "natural disaster",
            "natural_disaster",
            "earthquake",
            "flood",
            "hurricane",
            "typhoon",
            "wildfire",
        }
    ),
    frozenset(
        {
            "price change",
            "price_change",
            "price increase",
            "price cut",
            "pricing",
        }
    ),
    frozenset(
        {
            "capacity change",
            "capacity_change",
            "expansion",
            "plant closure",
            "production capacity",
        }
    ),
)

_SIGNAL_ALIAS_LOOKUP = {alias: group for group in SIGNAL_ALIAS_GROUPS for alias in group}


def normalize_signal_term(value: object) -> str:
    """Normalize a signal term while preserving phrase boundaries."""

    return re.sub(r"\s+", " ", str(value).strip().lower())


def expand_signal_terms(values: Iterable[object] | None) -> set[str]:
    """Return canonical signal terms plus user-facing aliases."""

    expanded: set[str] = set()
    queue = [
        term
        for value in values or []
        for term in _signal_term_variants(normalize_signal_term(value))
        if term
    ]

    while queue:
        term = queue.pop()
        if term in expanded:
            continue
        expanded.add(term)
        for alias in _SIGNAL_ALIAS_LOOKUP.get(term, frozenset()):
            for variant in _signal_term_variants(alias):
                if variant and variant not in expanded:
                    queue.append(variant)

    return expanded


def canonical_signal_tag(value: str | None) -> str | None:
    """Return the stored signal tag for exact tags or supported aliases."""

    if value is None:
        return None

    term = normalize_signal_term(value)
    if not term:
        return None

    for variant in _signal_term_variants(term):
        if variant in VALID_SIGNAL_TAGS:
            return variant

    expanded = expand_signal_terms([term])
    for tag in CANONICAL_SIGNAL_TAG_ORDER:
        if tag in expanded:
            return tag

    return None


def canonical_signal_tags(values: Iterable[str] | None) -> list[str]:
    """Canonicalize signal tags while preserving first-seen order."""

    tags: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        tag = canonical_signal_tag(value)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def text_matches_signal_terms(text: str, terms: Iterable[str] | None) -> bool:
    """Return True when text contains any signal phrase as a whole term."""

    normalized_text = normalize_signal_term(text)
    if not normalized_text:
        return False
    for term in expand_signal_terms(terms):
        if not term or len(term) < 3:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized_text):
            return True
    return False


def _signal_term_variants(term: str) -> set[str]:
    if not term:
        return set()
    underscored = term.replace(" ", "_")
    spaced = term.replace("_", " ")
    return {term, underscored, spaced}
