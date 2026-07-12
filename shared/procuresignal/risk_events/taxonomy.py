"""Procurement risk taxonomy and aliases."""

from __future__ import annotations

from collections.abc import Iterable

from procuresignal.signals.taxonomy import expand_signal_terms, normalize_signal_term

RISK_TYPE_ORDER = (
    "geopolitical",
    "regional_conflict",
    "supply_disruption",
    "tariff",
    "sanctions",
    "regulatory",
    "bankruptcy",
    "strike",
    "quality",
    "m_and_a",
    "currency",
    "logistics",
    "cybersecurity",
    "commodity",
)

RISK_ALIASES: dict[str, set[str]] = {
    "geopolitical": {
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
    },
    "regional_conflict": {
        "middle east",
        "mideast",
        "red sea",
        "gulf",
        "hormuz",
        "strait of hormuz",
        "suez",
        "iran",
        "iraq",
        "israel",
        "qatar",
        "saudi arabia",
        "uae",
        "united arab emirates",
        "yemen",
    },
    "supply_disruption": {
        "supply chain",
        "supply disruption",
        "supply shortage",
        "shortage",
        "factory shutdown",
        "facility closure",
        "production halt",
        "component shortage",
    },
    "tariff": {"tariff", "tariffs", "customs", "duties", "import duty", "trade duty"},
    "sanctions": {"sanction", "sanctions", "embargo", "export control", "blacklist"},
    "regulatory": {"regulation", "regulatory", "compliance", "legislation", "mandate"},
    "bankruptcy": {"bankruptcy", "chapter 11", "insolvency", "liquidation"},
    "strike": {"strike", "port strike", "labor dispute", "labour dispute", "walkout"},
    "quality": {"quality", "quality issue", "recall", "defect"},
    "m_and_a": {"m&a", "m_and_a", "merger", "acquisition", "takeover", "deal"},
    "currency": {"currency", "foreign exchange", "fx", "euro", "exchange rate"},
    "logistics": {"logistics", "port delay", "shipping delay", "transport disruption"},
    "cybersecurity": {"cyberattack", "cyber attack", "ransomware", "data breach"},
    "commodity": {"commodity", "raw material", "critical minerals", "metals", "energy price"},
}

SEVERITY_BY_RISK_TYPE = {
    "bankruptcy": "critical",
    "geopolitical": "high",
    "regional_conflict": "high",
    "sanctions": "high",
    "supply_disruption": "high",
    "tariff": "medium",
    "strike": "medium",
    "quality": "medium",
    "regulatory": "medium",
    "m_and_a": "medium",
    "currency": "medium",
    "logistics": "medium",
    "cybersecurity": "high",
    "commodity": "medium",
}

RECOMMENDATIONS = {
    "bankruptcy": "Review supplier continuity and alternate sourcing options before placing new orders.",
    "geopolitical": "Review supplier exposure in this region before placing large orders.",
    "regional_conflict": "Review supplier exposure in this region before placing large orders.",
    "sanctions": "Review compliance exposure before engaging affected suppliers.",
    "supply_disruption": "Review alternate suppliers and inventory coverage.",
    "tariff": "Check landed cost and tariff exposure before confirming new purchase orders.",
    "strike": "Review logistics buffers and supplier delivery commitments.",
    "quality": "Review quality exposure before approving new supplier shipments.",
    "regulatory": "Review compliance requirements before changing supplier commitments.",
    "m_and_a": "Review ownership changes and possible contract or continuity impact.",
    "currency": "Compare timing with the EUR monitor before committing spend.",
    "logistics": "Review transit routes, buffers, and alternate logistics options.",
    "cybersecurity": "Review supplier operational and data exposure before sharing sensitive information.",
    "commodity": "Review price exposure and inventory coverage for affected materials.",
}

_ALIAS_TO_TYPE = {
    normalize_signal_term(alias): risk_type
    for risk_type, aliases in RISK_ALIASES.items()
    for alias in aliases | {risk_type}
}


def normalize_risk_type(value: str | None) -> str | None:
    """Return the canonical risk type for a free-text value."""

    if not value:
        return None
    normalized = normalize_signal_term(value)
    if normalized in _ALIAS_TO_TYPE:
        return _ALIAS_TO_TYPE[normalized]
    expanded = expand_signal_terms([normalized])
    for risk_type in RISK_TYPE_ORDER:
        if expanded & risk_terms_for([risk_type]):
            return risk_type
    return None


def risk_terms_for(values: Iterable[str] | None) -> set[str]:
    """Expand risk types or natural terms into all searchable aliases."""

    terms: set[str] = set()
    for value in values or []:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = normalize_signal_term(value)
        risk_type = _ALIAS_TO_TYPE.get(normalized, normalized)
        aliases = RISK_ALIASES.get(risk_type, {normalized})
        expanded_values = [risk_type, *aliases]
        if risk_type == "geopolitical":
            expanded_values.extend(["regional_conflict", *RISK_ALIASES["regional_conflict"]])
        terms.update(expand_signal_terms(expanded_values))
    return {term for term in terms if term}
