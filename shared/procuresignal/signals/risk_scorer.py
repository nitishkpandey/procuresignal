from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class ImpactScore:
    procurement_impact: float
    supply_chain_impact: float
    compliance_impact: float
    pricing_impact: float
    overall_risk_score: float


class RiskScorer:
    """Scores the impact and risk of detected signals."""

    def score_signal(
        self, signal_type: str, severity: str, affected_entities: List[str]
    ) -> ImpactScore:
        base_scores = {
            "bankruptcy": {
                "procurement": 0.95,
                "supply_chain": 0.90,
                "compliance": 0.60,
                "pricing": 0.70,
            },
            "m_and_a": {
                "procurement": 0.80,
                "supply_chain": 0.75,
                "compliance": 0.70,
                "pricing": 0.65,
            },
            "tariff": {
                "procurement": 0.85,
                "supply_chain": 0.70,
                "compliance": 0.90,
                "pricing": 0.95,
            },
            "strike": {
                "procurement": 0.70,
                "supply_chain": 0.85,
                "compliance": 0.40,
                "pricing": 0.50,
            },
            "regulatory": {
                "procurement": 0.75,
                "supply_chain": 0.50,
                "compliance": 0.95,
                "pricing": 0.40,
            },
            "supply_disruption": {
                "procurement": 0.90,
                "supply_chain": 0.95,
                "compliance": 0.50,
                "pricing": 0.80,
            },
        }

        scores = base_scores.get(
            signal_type,
            {"procurement": 0.5, "supply_chain": 0.5, "compliance": 0.5, "pricing": 0.5},
        )

        severity_multiplier = {
            "critical": 1.0,
            "high": 0.85,
            "medium": 0.65,
            "low": 0.40,
        }.get(severity, 0.5)

        for key in list(scores.keys()):
            scores[key] = min(1.0, scores[key] * severity_multiplier)

        overall = sum(scores.values()) / len(scores)

        return ImpactScore(
            procurement_impact=scores.get("procurement", 0.0),
            supply_chain_impact=scores.get("supply_chain", 0.0),
            compliance_impact=scores.get("compliance", 0.0),
            pricing_impact=scores.get("pricing", 0.0),
            overall_risk_score=overall,
        )
