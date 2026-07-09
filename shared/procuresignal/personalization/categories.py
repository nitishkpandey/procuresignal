"""Category normalization helpers for personalization."""

from collections.abc import Iterable

CANONICAL_CATEGORIES = {
    "automotive",
    "electronics",
    "chemicals",
    "energy",
    "manufacturing",
    "logistics",
    "regulatory",
    "general",
}

CATEGORY_ALIASES: dict[str, str] = {
    "auto": "automotive",
    "automobile": "automotive",
    "automobiles": "automotive",
    "car": "automotive",
    "cars": "automotive",
    "ev": "automotive",
    "evs": "automotive",
    "vehicle": "automotive",
    "vehicles": "automotive",
    "chip": "electronics",
    "chips": "electronics",
    "electronic": "electronics",
    "semiconductor": "electronics",
    "semiconductors": "electronics",
    "tech": "electronics",
    "technology": "electronics",
    "chemical": "chemicals",
    "freight": "logistics",
    "shipping": "logistics",
    "supply chain": "logistics",
    "supply_chain": "logistics",
    "transport": "logistics",
    "transportation": "logistics",
    "factory": "manufacturing",
    "factories": "manufacturing",
    "industrial": "manufacturing",
    "industry": "manufacturing",
    "compliance": "regulatory",
    "legal": "regulatory",
    "regulation": "regulatory",
    "regulations": "regulatory",
    "oil": "energy",
    "gas": "energy",
    "power": "energy",
    "renewable": "energy",
    "renewables": "energy",
    "utility": "energy",
    "utilities": "energy",
}

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "automotive": {
        "automotive",
        "auto",
        "automobile",
        "car",
        "cars",
        "ev",
        "fleet",
        "mobility",
        "vehicle",
        "vehicles",
    },
    "electronics": {
        "ai",
        "chip",
        "chips",
        "electronics",
        "hardware",
        "memory",
        "semiconductor",
        "semiconductors",
        "software",
        "technology",
    },
    "chemicals": {
        "chemical",
        "chemicals",
        "fertilizer",
        "materials",
        "plastics",
        "polymer",
        "resin",
    },
    "energy": {
        "battery",
        "electricity",
        "energy",
        "gas",
        "oil",
        "power",
        "renewable",
        "renewables",
        "solar",
        "utility",
        "wind",
    },
    "manufacturing": {
        "factory",
        "factories",
        "industrial",
        "industry",
        "manufacturing",
        "plant",
        "production",
    },
    "logistics": {
        "cargo",
        "freight",
        "logistics",
        "port",
        "shipping",
        "supply",
        "transport",
        "transportation",
        "warehouse",
    },
    "regulatory": {
        "compliance",
        "law",
        "legal",
        "policy",
        "regulation",
        "regulations",
        "regulatory",
        "rules",
        "sanctions",
        "tariff",
        "trade",
    },
}


def normalize_category_key(value: object) -> str:
    """Return a stable lowercase key for category matching."""

    text = str(value).strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(text.split())


def canonical_category(value: object) -> str:
    """Map common user-entered category names to the article taxonomy."""

    key = normalize_category_key(value)
    if key in CANONICAL_CATEGORIES:
        return key
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]

    tokens = set(key.split())
    scores = {category: len(tokens & keywords) for category, keywords in CATEGORY_KEYWORDS.items()}
    best_category, score = max(scores.items(), key=lambda item: item[1])
    return best_category if score > 0 else key


def canonical_category_list(values: Iterable[object] | None) -> list[str]:
    """Canonicalize category values while preserving input order."""

    normalized: list[str] = []
    for value in values or []:
        category = canonical_category(value)
        if category and category not in normalized:
            normalized.append(category)
    return normalized


def canonical_category_set(values: Iterable[object] | None) -> set[str]:
    """Canonicalize category values for set operations."""

    return set(canonical_category_list(values))
