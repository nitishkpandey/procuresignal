# Phase 4: Procurement Signal Engine — Complete Guide

## Overview

Phase 4 is the heart of ProcureSignal—where you implement real domain logic to detect and analyze procurement signals. These signals indicate events that may impact supply chains, pricing, compliance, or business operations.

### Key Procurement Signals to Detect

1. **Bankruptcy & Insolvency** — Company financial distress
2. **Mergers & Acquisitions (M&A)** — Corporate consolidation/restructuring
3. **Tariffs & Trade Policy** — Import/export duties and restrictions
4. **Labor Strikes** — Work stoppages affecting production
5. **Regulatory Changes** — Compliance requirements
6. **Supply Chain Disruptions** — Logistics/production halts
7. **Natural Disasters** — Environmental impacts on suppliers
8. **Price Changes** — Commodity/material cost fluctuations
9. **Executive Changes** — Leadership transitions affecting strategy
10. **Capacity Changes** — Expansions or shutdowns

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   ProcureSignal Architecture                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         Data Collection Layer (Phase 1-2)           │   │
│  │  (News APIs, RSS, Web Scraping, Social Media)       │   │
│  └────────────────────┬─────────────────────────────────┘   │
│                       │                                       │
│  ┌────────────────────▼─────────────────────────────────┐   │
│  │       Data Normalization & Deduplication (Phase 3)  │   │
│  │  (Parser, Deduplicator, Language Detection)         │   │
│  └────────────────────┬─────────────────────────────────┘   │
│                       │                                       │
│  ┌────────────────────▼─────────────────────────────────┐   │
│  │    *** PHASE 4: SIGNAL DETECTION ENGINE ***         │   │
│  │  ┌────────────────────────────────────────────────┐ │   │
│  │  │  Signal Classifiers & Analyzers               │ │   │
│  │  │  - Bankruptcy Detector                        │ │   │
│  │  │  - M&A Analyzer                               │ │   │
│  │  │  - Regulatory Change Parser                   │ │   │
│  │  │  - Labor Event Detector                       │ │   │
│  │  │  - Tariff Classifier                          │ │   │
│  │  │  - Sentiment/Impact Analyzer                  │ │   │
│  │  └────────────────────────────────────────────────┘ │   │
│  │  ┌────────────────────────────────────────────────┐ │   │
│  │  │  Signal Enrichment & Validation               │ │   │
│  │  │  - Entity Resolution (Companies/People)       │ │   │
│  │  │  - Impact Assessment                          │ │   │
│  │  │  - Risk Scoring                               │ │   │
│  │  │  - Supply Chain Mapping                       │ │   │
│  │  └────────────────────────────────────────────────┘ │   │
│  └────────────────────┬─────────────────────────────────┘   │
│                       │                                       │
│  ┌────────────────────▼─────────────────────────────────┐   │
│  │    Signal Persistence & Retrieval (Phase 5)         │   │
│  │  (Database, Caching, APIs)                          │   │
│  └────────────────────┬─────────────────────────────────┘   │
│                       │                                       │
│  ┌────────────────────▼─────────────────────────────────┐   │
│  │    User Alerts & Notifications (Phase 6)            │   │
│  │  (Email, Webhook, Dashboard)                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 4 Implementation Plan

### 1. Database Schema Additions

Create tables to store detected signals:

```sql
-- Signals table
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type VARCHAR(50) NOT NULL,  -- bankruptcy, m&a, tariff, strike, etc.
    entity_id UUID REFERENCES entities(id),
    article_id UUID REFERENCES articles(id),
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    severity VARCHAR(20),  -- high, medium, low
    impact_areas TEXT[],  -- procurement, supply_chain, compliance, pricing
    raw_signal JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Signal metadata
CREATE TABLE signal_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    key VARCHAR(255),
    value TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Supply chain impact
CREATE TABLE signal_supply_chain_impact (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    affected_entity_id UUID REFERENCES entities(id),
    relationship_type VARCHAR(100),  -- supplier, competitor, customer, etc.
    impact_score FLOAT CHECK (impact_score >= 0 AND impact_score <= 1),
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 2. Core Signal Detection Modules

#### A. Signal Type Classifier

```python
# shared/procuresignal/signals/classifier.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

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
    entity_id: Optional[str]
    confidence: float  # 0.0-1.0
    severity: SignalSeverity
    headline: str
    description: str
    impact_areas: list[str]  # procurement, supply_chain, compliance, pricing, etc.
    raw_data: Dict[str, Any]
    source_article_id: Optional[str] = None
    metadata: Dict[str, Any] = None

class SignalClassifier:
    """Classifies articles into signal types."""

    def classify(self, article_text: str, headline: str) -> list[Signal]:
        """
        Analyze article and return detected signals.

        Returns:
            List of detected signals with confidence scores
        """
        signals = []

        # Check each signal type
        signals.extend(self._check_bankruptcy(article_text, headline))
        signals.extend(self._check_m_and_a(article_text, headline))
        signals.extend(self._check_tariff(article_text, headline))
        signals.extend(self._check_strike(article_text, headline))
        signals.extend(self._check_regulatory(article_text, headline))
        signals.extend(self._check_supply_disruption(article_text, headline))

        return signals

    def _check_bankruptcy(self, text: str, headline: str) -> list[Signal]:
        """Detect bankruptcy signals."""
        bankruptcy_keywords = [
            "bankruptcy", "insolvency", "filed for bankruptcy",
            "chapter 11", "chapter 7", "debt restructuring",
            "going out of business", "liquidation", "receivership"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in bankruptcy_keywords):
            signals.append(Signal(
                signal_type=SignalType.BANKRUPTCY,
                entity_name="",  # Extract from text
                entity_id=None,
                confidence=0.85,  # Adjust based on keyword density
                severity=SignalSeverity.CRITICAL,
                headline=headline,
                description=text[:500],
                impact_areas=["procurement", "supply_chain", "compliance"],
                raw_data={"keywords_matched": bankruptcy_keywords}
            ))

        return signals

    def _check_m_and_a(self, text: str, headline: str) -> list[Signal]:
        """Detect M&A signals."""
        ma_keywords = [
            "acquired", "merger", "acquisition", "merged with",
            "combine", "consolidation", "buyout", "takeover",
            "purchase agreement", "deal"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in ma_keywords):
            signals.append(Signal(
                signal_type=SignalType.M_AND_A,
                entity_name="",
                entity_id=None,
                confidence=0.80,
                severity=SignalSeverity.HIGH,
                headline=headline,
                description=text[:500],
                impact_areas=["supply_chain", "pricing", "compliance"],
                raw_data={"keywords_matched": ma_keywords}
            ))

        return signals

    def _check_tariff(self, text: str, headline: str) -> list[Signal]:
        """Detect tariff/trade policy signals."""
        tariff_keywords = [
            "tariff", "import duty", "export restriction",
            "trade war", "sanctions", "embargo",
            "trade agreement", "customs"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in tariff_keywords):
            signals.append(Signal(
                signal_type=SignalType.TARIFF,
                entity_name="",
                entity_id=None,
                confidence=0.78,
                severity=SignalSeverity.HIGH,
                headline=headline,
                description=text[:500],
                impact_areas=["pricing", "procurement", "compliance"],
                raw_data={"keywords_matched": tariff_keywords}
            ))

        return signals

    def _check_strike(self, text: str, headline: str) -> list[Signal]:
        """Detect labor strike signals."""
        strike_keywords = [
            "strike", "labor strike", "workers strike",
            "work stoppage", "union strike", "walkout",
            "industrial action"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in strike_keywords):
            signals.append(Signal(
                signal_type=SignalType.STRIKE,
                entity_name="",
                entity_id=None,
                confidence=0.88,
                severity=SignalSeverity.MEDIUM,
                headline=headline,
                description=text[:500],
                impact_areas=["supply_chain", "procurement"],
                raw_data={"keywords_matched": strike_keywords}
            ))

        return signals

    def _check_regulatory(self, text: str, headline: str) -> list[Signal]:
        """Detect regulatory change signals."""
        regulatory_keywords = [
            "regulation", "compliance", "mandate",
            "legislation", "law change", "executive order",
            "policy change", "requirement"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in regulatory_keywords):
            signals.append(Signal(
                signal_type=SignalType.REGULATORY,
                entity_name="",
                entity_id=None,
                confidence=0.75,
                severity=SignalSeverity.MEDIUM,
                headline=headline,
                description=text[:500],
                impact_areas=["compliance", "procurement"],
                raw_data={"keywords_matched": regulatory_keywords}
            ))

        return signals

    def _check_supply_disruption(self, text: str, headline: str) -> list[Signal]:
        """Detect supply chain disruption signals."""
        disruption_keywords = [
            "supply chain disruption", "logistics delay",
            "port closure", "transportation halt",
            "facility closure", "production halt",
            "shortage", "supply shortage"
        ]

        text_lower = text.lower()
        headline_lower = headline.lower()

        signals = []
        if any(kw in text_lower or kw in headline_lower for kw in disruption_keywords):
            signals.append(Signal(
                signal_type=SignalType.SUPPLY_DISRUPTION,
                entity_name="",
                entity_id=None,
                confidence=0.82,
                severity=SignalSeverity.HIGH,
                headline=headline,
                description=text[:500],
                impact_areas=["supply_chain", "procurement"],
                raw_data={"keywords_matched": disruption_keywords}
            ))

        return signals
```

#### B. Entity Resolution & Company Matching

```python
# shared/procuresignal/signals/entity_resolver.py

from typing import Optional, List, Tuple
from fuzzywuzzy import fuzz
from dataclasses import dataclass

@dataclass
class ResolvedEntity:
    entity_id: str
    entity_name: str
    match_confidence: float
    entity_type: str  # company, person, location, etc.

class EntityResolver:
    """Resolves entity names to database records."""

    def __init__(self, db_session):
        self.db = db_session

    def resolve_company(self, company_name: str, context: Optional[str] = None) -> Optional[ResolvedEntity]:
        """
        Match a company name to database record.

        Args:
            company_name: Name to resolve
            context: Optional context (location, industry, etc.) to improve matching

        Returns:
            Resolved entity or None if no match
        """
        if not company_name:
            return None

        # Try exact match first
        exact_match = self._exact_match(company_name)
        if exact_match:
            return exact_match

        # Try fuzzy matching
        candidates = self._fuzzy_match(company_name, threshold=0.75)
        if candidates:
            return candidates[0]  # Return best match

        return None

    def _exact_match(self, name: str) -> Optional[ResolvedEntity]:
        """Check for exact company name match."""
        # Query database for exact match
        # Implementation depends on your database schema
        pass

    def _fuzzy_match(self, name: str, threshold: int = 75) -> List[ResolvedEntity]:
        """Find fuzzy matches for company name."""
        # Query all companies and rank by similarity
        # Implementation depends on your database schema
        pass
```

#### C. Risk & Impact Scorer

```python
# shared/procuresignal/signals/risk_scorer.py

from typing import Dict, List
from dataclasses import dataclass

@dataclass
class ImpactScore:
    procurement_impact: float  # 0-1
    supply_chain_impact: float  # 0-1
    compliance_impact: float  # 0-1
    pricing_impact: float  # 0-1
    overall_risk_score: float  # 0-1

class RiskScorer:
    """Scores the impact and risk of detected signals."""

    def score_signal(self, signal_type: str, severity: str,
                    affected_entities: List[str]) -> ImpactScore:
        """
        Calculate impact scores for a signal.

        Args:
            signal_type: Type of signal (bankruptcy, m&a, tariff, etc.)
            severity: Severity level (critical, high, medium, low)
            affected_entities: List of affected company names

        Returns:
            ImpactScore with calculated metrics
        """

        # Base scores by signal type
        base_scores = {
            "bankruptcy": {"procurement": 0.95, "supply_chain": 0.90, "compliance": 0.60, "pricing": 0.70},
            "m_and_a": {"procurement": 0.80, "supply_chain": 0.75, "compliance": 0.70, "pricing": 0.65},
            "tariff": {"procurement": 0.85, "supply_chain": 0.70, "compliance": 0.90, "pricing": 0.95},
            "strike": {"procurement": 0.70, "supply_chain": 0.85, "compliance": 0.40, "pricing": 0.50},
            "regulatory": {"procurement": 0.75, "supply_chain": 0.50, "compliance": 0.95, "pricing": 0.40},
            "supply_disruption": {"procurement": 0.90, "supply_chain": 0.95, "compliance": 0.50, "pricing": 0.80},
        }

        # Get base scores
        scores = base_scores.get(signal_type, {
            "procurement": 0.5, "supply_chain": 0.5, "compliance": 0.5, "pricing": 0.5
        })

        # Adjust by severity
        severity_multiplier = {
            "critical": 1.0,
            "high": 0.85,
            "medium": 0.65,
            "low": 0.40
        }.get(severity, 0.5)

        # Apply multiplier
        for key in scores:
            scores[key] = min(1.0, scores[key] * severity_multiplier)

        # Calculate overall score
        overall = sum(scores.values()) / len(scores)

        return ImpactScore(
            procurement_impact=scores.get("procurement", 0),
            supply_chain_impact=scores.get("supply_chain", 0),
            compliance_impact=scores.get("compliance", 0),
            pricing_impact=scores.get("pricing", 0),
            overall_risk_score=overall
        )
```

### 3. Signal Processing Worker Task

Add to your Celery worker to process signals:

```python
# worker/tasks.py

from celery import shared_task
from shared.procuresignal.signals.classifier import SignalClassifier
from shared.procuresignal.signals.entity_resolver import EntityResolver
from shared.procuresignal.signals.risk_scorer import RiskScorer
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_article_for_signals(article_id: str, article_text: str, headline: str):
    """
    Process an article to detect procurement signals.

    This task:
    1. Classifies the article into signal types
    2. Resolves entity names
    3. Scores risk/impact
    4. Stores signals in database
    """
    try:
        classifier = SignalClassifier()
        signals = classifier.classify(article_text, headline)

        # Process each detected signal
        for signal in signals:
            logger.info(f"Detected {signal.signal_type} signal in article {article_id}")

            # Resolve entity
            resolver = EntityResolver()
            resolved_entity = resolver.resolve_company(signal.entity_name)

            if resolved_entity:
                signal.entity_id = resolved_entity.entity_id
                signal.entity_name = resolved_entity.entity_name

            # Score impact
            scorer = RiskScorer()
            impact = scorer.score_signal(
                signal.signal_type.value,
                signal.severity.value,
                [signal.entity_name]
            )

            # Store signal
            _store_signal(article_id, signal, impact)

        return {"signals_detected": len(signals), "article_id": article_id}

    except Exception as e:
        logger.error(f"Error processing signals for article {article_id}: {str(e)}")
        raise

def _store_signal(article_id: str, signal, impact):
    """Store signal in database."""
    # Implementation depends on your ORM
    pass
```

### 4. API Endpoints for Signal Retrieval

```python
# api/api/routers/signals.py

from fastapi import APIRouter, Query, Depends
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/api/signals", tags=["signals"])

@router.get("/")
async def list_signals(
    signal_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50),
):
    """
    List detected signals with optional filtering.

    Query Parameters:
    - signal_type: Filter by signal type (bankruptcy, m&a, tariff, etc.)
    - entity_id: Filter by affected entity
    - severity: Filter by severity (critical, high, medium, low)
    - skip: Pagination offset
    - limit: Pagination limit

    Returns:
        List of signals with metadata
    """
    pass

@router.get("/{signal_id}")
async def get_signal(signal_id: str):
    """Get details of a specific signal."""
    pass

@router.get("/entity/{entity_id}/signals")
async def get_entity_signals(entity_id: str):
    """Get all signals related to an entity."""
    pass

@router.post("/{signal_id}/acknowledge")
async def acknowledge_signal(signal_id: str):
    """Mark a signal as acknowledged/reviewed."""
    pass

@router.get("/stats/summary")
async def get_signal_stats():
    """Get summary statistics of signals."""
    pass
```

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_signal_classifier.py

import pytest
from shared.procuresignal.signals.classifier import SignalClassifier, SignalType

@pytest.fixture
def classifier():
    return SignalClassifier()

def test_bankruptcy_detection(classifier):
    """Test bankruptcy signal detection."""
    article = "Company ABC filed for Chapter 11 bankruptcy protection."
    signals = classifier.classify(article, "ABC Inc Files Bankruptcy")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.BANKRUPTCY
    assert signals[0].confidence > 0.75

def test_m_and_a_detection(classifier):
    """Test M&A signal detection."""
    article = "Tech giant XYZ has acquired competitor 123 Corp for $5 billion."
    signals = classifier.classify(article, "XYZ Acquires 123 Corp")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.M_AND_A

def test_tariff_detection(classifier):
    """Test tariff signal detection."""
    article = "Government announces new 25% tariff on imported steel."
    signals = classifier.classify(article, "New Steel Tariffs Announced")

    assert len(signals) > 0
    assert signals[0].signal_type == SignalType.TARIFF

def test_no_false_positives(classifier):
    """Ensure generic articles don't trigger false positives."""
    article = "The weather is nice today and the market is down slightly."
    signals = classifier.classify(article, "Weather and Markets")

    assert len(signals) == 0
```

### Integration Tests

```python
# tests/integration/test_signal_workflow.py

@pytest.mark.asyncio
async def test_end_to_end_signal_detection():
    """Test complete signal detection workflow."""
    # 1. Create test article
    # 2. Trigger signal processing
    # 3. Verify signals are stored
    # 4. Verify entity resolution
    # 5. Verify risk scoring
    pass
```

---

## Implementation Checklist

- [ ] Create database schema for signals
- [ ] Implement `SignalClassifier` with all signal types
- [ ] Implement `EntityResolver` with fuzzy matching
- [ ] Implement `RiskScorer` with impact calculations
- [ ] Create Celery task for signal processing
- [ ] Build API endpoints for signal retrieval
- [ ] Write comprehensive tests (unit + integration)
- [ ] Add signal statistics dashboard
- [ ] Set up monitoring and alerting
- [ ] Document signal definitions and thresholds

---

## Next Steps

1. **Start with the database schema** — Create migrations for signals tables
2. **Implement the classifier** — Start with 2-3 signal types, expand later
3. **Add entity resolution** — Use fuzzy matching to link signals to companies
4. **Integrate with worker** — Add Celery task to process articles
5. **Build API** — Expose signals via REST API
6. **Add monitoring** — Track signal quality and false positive rates

---

## Resources & References

- **Natural Language Processing**: NLTK, spaCy
- **Fuzzy Matching**: FuzzyWuzzy, Levenshtein
- **ML Classification**: scikit-learn, transformers (if upgrading to NLP models)
- **Celery**: Task queue for async processing
- **PostgreSQL**: JSONB for flexible signal metadata

---

## Phase 4 Success Criteria

✅ At least 5 signal types detected with >80% accuracy
✅ Entity resolution working for 90% of mentions
✅ Risk scoring aligned with business impact
✅ API endpoints responding in <500ms
✅ >90% test coverage for core modules
✅ Signal quality monitored and improving

Good luck! 🚀
