"""Lightweight entity extraction fallback for suppliers and regions."""

from __future__ import annotations

import re
from collections.abc import Iterable

REGION_ALIASES: dict[str, str] = {
    "us": "United States",
    "u.s.": "United States",
    "usa": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "eu": "European Union",
    "european union": "European Union",
    "europe": "Europe",
    "asia": "Asia",
    "china": "China",
    "germany": "Germany",
    "france": "France",
    "italy": "Italy",
    "poland": "Poland",
    "india": "India",
    "japan": "Japan",
    "mexico": "Mexico",
    "canada": "Canada",
    "brazil": "Brazil",
    "vietnam": "Vietnam",
    "taiwan": "Taiwan",
    "south korea": "South Korea",
    "korea": "South Korea",
}

KNOWN_SUPPLIERS = {
    "Anthropic",
    "Apple",
    "Bosch",
    "Critical Metals",
    "Ferrari",
    "Genuine Parts",
    "Mercedes",
    "Motherson",
    "Nexans",
    "OpenAI",
    "O'Reilly Automotive",
    "Siemens",
    "Toyota",
    "Volkswagen",
}

COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z&'.-]*(?:\s+[A-Z][A-Za-z&'.-]*){0,4}\s+"
    r"(?:AG|Corp\.?|Corporation|Co\.?|Company|GmbH|Group|Inc\.?|Ltd\.?|PLC|SA|SE))\b"
)


def merge_entities(*groups: Iterable[str] | None) -> list[str]:
    """Merge entity lists while preserving order."""

    merged: list[str] = []
    for group in groups:
        for value in group or []:
            text = str(value).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def extract_regions_from_text(text: str) -> list[str]:
    """Extract known procurement-relevant regions from text."""

    lowered = text.lower()
    regions: list[str] = []
    for alias, canonical in REGION_ALIASES.items():
        if (
            re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered)
            and canonical not in regions
        ):
            regions.append(canonical)
    return regions


def extract_suppliers_from_text(text: str) -> list[str]:
    """Extract obvious company/supplier names from text."""

    suppliers: list[str] = []
    for supplier in sorted(KNOWN_SUPPLIERS, key=len, reverse=True):
        if (
            re.search(rf"(?<![A-Za-z]){re.escape(supplier)}(?![A-Za-z])", text)
            and supplier not in suppliers
        ):
            suppliers.append(supplier)

    for match in COMPANY_SUFFIX_PATTERN.finditer(text):
        name = match.group(1).strip(" .")
        if name and name not in suppliers:
            suppliers.append(name)

    return suppliers
