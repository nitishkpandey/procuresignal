"""Category normalization helpers for personalization."""

from collections.abc import Iterable


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


def normalize_category_key(value: object) -> str:
    """Return a stable lowercase key for category matching."""

    text = str(value).strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(text.split())


def canonical_category(value: object) -> str:
    """Map common user-entered category names to the article taxonomy."""

    key = normalize_category_key(value)
    return CATEGORY_ALIASES.get(key, key)


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
