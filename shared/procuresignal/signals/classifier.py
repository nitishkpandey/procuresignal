from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalType(Enum):
    BANKRUPTCY = "bankruptcy"
    M_AND_A = "m_and_a"
    TARIFF = "tariff"
    STRIKE = "strike"
    REGULATORY = "regulatory"
    SUPPLY_DISRUPTION = "supply_disruption"
    NATURAL_DISASTER = "natural_disaster"
    PRICE_CHANGE = "price_change"
    EXECUTIVE_CHANGE = "executive_change"
    CAPACITY_CHANGE = "capacity_change"


class SignalSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Signal:
    signal_type: SignalType
    entity_name: str
    entity_id: Optional[str] = None
    confidence: float = 0.0
    severity: SignalSeverity = SignalSeverity.LOW
    headline: str = ""
    description: str = ""
    impact_areas: Optional[List[str]] = None
    raw_data: Optional[Dict[str, Any]] = None
    source_article_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SignalClassifier:
    """Classifies articles into signal types using rule-based checks.

    This is intentionally lightweight and designed to be replaced by
    an ML/NLP model later. Current implementation uses keyword matching
    and returns a list of `Signal` instances.
    """

    def classify(self, article_text: str, headline: str) -> List[Signal]:
        signals: List[Signal] = []

        signals.extend(self._check_bankruptcy(article_text, headline))
        signals.extend(self._check_m_and_a(article_text, headline))
        signals.extend(self._check_tariff(article_text, headline))
        signals.extend(self._check_strike(article_text, headline))
        signals.extend(self._check_regulatory(article_text, headline))
        signals.extend(self._check_supply_disruption(article_text, headline))

        return signals

    def _check_bankruptcy(self, text: str, headline: str) -> List[Signal]:
        bankruptcy_keywords = [
            "bankruptcy",
            "insolvency",
            "filed for bankruptcy",
            "chapter 11",
            "chapter 7",
            "debt restructuring",
            "going out of business",
            "liquidation",
            "receivership",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in bankruptcy_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.BANKRUPTCY,
                    entity_name="",
                    entity_id=None,
                    confidence=0.85,
                    severity=SignalSeverity.CRITICAL,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["procurement", "supply_chain", "compliance"],
                    raw_data={"keywords_matched": bankruptcy_keywords},
                )
            )

        return signals

    def _check_m_and_a(self, text: str, headline: str) -> List[Signal]:
        ma_keywords = [
            "acquired",
            "merger",
            "acquisition",
            "merged with",
            "combine",
            "consolidation",
            "buyout",
            "takeover",
            "purchase agreement",
            "deal",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in ma_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.M_AND_A,
                    entity_name="",
                    entity_id=None,
                    confidence=0.80,
                    severity=SignalSeverity.HIGH,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["supply_chain", "pricing", "compliance"],
                    raw_data={"keywords_matched": ma_keywords},
                )
            )

        return signals

    def _check_tariff(self, text: str, headline: str) -> List[Signal]:
        tariff_keywords = [
            "tariff",
            "import duty",
            "export restriction",
            "trade war",
            "sanctions",
            "embargo",
            "trade agreement",
            "customs",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in tariff_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.TARIFF,
                    entity_name="",
                    entity_id=None,
                    confidence=0.78,
                    severity=SignalSeverity.HIGH,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["pricing", "procurement", "compliance"],
                    raw_data={"keywords_matched": tariff_keywords},
                )
            )

        return signals

    def _check_strike(self, text: str, headline: str) -> List[Signal]:
        strike_keywords = [
            "strike",
            "labor strike",
            "workers strike",
            "work stoppage",
            "union strike",
            "walkout",
            "industrial action",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in strike_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.STRIKE,
                    entity_name="",
                    entity_id=None,
                    confidence=0.88,
                    severity=SignalSeverity.MEDIUM,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["supply_chain", "procurement"],
                    raw_data={"keywords_matched": strike_keywords},
                )
            )

        return signals

    def _check_regulatory(self, text: str, headline: str) -> List[Signal]:
        regulatory_keywords = [
            "regulation",
            "compliance",
            "mandate",
            "legislation",
            "law change",
            "executive order",
            "policy change",
            "requirement",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in regulatory_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.REGULATORY,
                    entity_name="",
                    entity_id=None,
                    confidence=0.75,
                    severity=SignalSeverity.MEDIUM,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["compliance", "procurement"],
                    raw_data={"keywords_matched": regulatory_keywords},
                )
            )

        return signals

    def _check_supply_disruption(self, text: str, headline: str) -> List[Signal]:
        disruption_keywords = [
            "supply chain disruption",
            "logistics delay",
            "port closure",
            "transportation halt",
            "facility closure",
            "production halt",
            "shortage",
            "supply shortage",
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals: List[Signal] = []
        if any(kw in text_lower or kw in headline_lower for kw in disruption_keywords):
            signals.append(
                Signal(
                    signal_type=SignalType.SUPPLY_DISRUPTION,
                    entity_name="",
                    entity_id=None,
                    confidence=0.82,
                    severity=SignalSeverity.HIGH,
                    headline=headline,
                    description=text[:500],
                    impact_areas=["supply_chain", "procurement"],
                    raw_data={"keywords_matched": disruption_keywords},
                )
            )

        return signals
