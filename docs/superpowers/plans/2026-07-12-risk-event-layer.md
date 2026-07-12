# Risk Event Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic-first Risk Events layer that turns processed procurement news into explainable, preference-aware risk events with a compact UI.

**Architecture:** Add a focused `procuresignal.risk_events` package for taxonomy, detection, and persistence. Store events in a new SQLAlchemy model and expose them through FastAPI routes consumed by a new Next.js Risk Events page. Keep OpenAI out of the default detection path; use existing translation only for user-facing non-English event text.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pytest, Celery, APScheduler, Next.js 14, TypeScript, React, Vitest, Tailwind.

## Global Constraints

- Work on `codex/risk-event-layer-design` or a child branch, not directly on `main`.
- Do not change SupplierMind files or behavior.
- Do not call OpenAI for every article in risk detection.
- Use deterministic taxonomy, aliases, article metadata, and preferences first.
- Jobs must be idempotent and safe to rerun.
- Existing Feed, Preferences, Chat, Currency, language, and login flows must keep working.
- Display confidence in the UI as only a number with `%`.
- Keep UI compact and professional, matching the existing ProcureSignal app shell.

---

## File Structure

- Create `shared/procuresignal/risk_events/__init__.py`: package exports.
- Create `shared/procuresignal/risk_events/taxonomy.py`: risk taxonomy, aliases, severity defaults, recommendation copy.
- Create `shared/procuresignal/risk_events/detector.py`: converts processed/raw article pairs into `RiskEventCandidate` objects.
- Create `shared/procuresignal/risk_events/persistence.py`: idempotent DB upsert and batch generation.
- Create `shared/procuresignal/models/risk_events.py`: SQLAlchemy `RiskEvent` model.
- Modify `shared/procuresignal/models/__init__.py`: export `RiskEvent`.
- Create `migrations/versions/d4e5f6_add_risk_events.py`: Alembic migration.
- Create `api/schemas/risk_event.py`: Pydantic response/update schemas.
- Create `api/routers/risk_events.py`: list/detail/status endpoints.
- Modify `api/main.py`: include risk events router.
- Modify `api/translation.py`: translate risk-event evidence and recommendation for non-English users.
- Modify `worker/tasks.py`: add `generate_risk_events_task`.
- Modify `worker/celery_config.py`: route/schedule risk event generation.
- Modify `api/scheduler.py`: enqueue risk event generation in APScheduler.
- Modify `frontend/lib/types.ts`: risk event TypeScript types.
- Modify `frontend/lib/api.ts`: risk event API client functions.
- Modify `frontend/lib/i18n.ts`: nav and Risk Events page labels.
- Modify `frontend/components/header.tsx`: add `Risk Events` nav item.
- Create `frontend/components/risk-events-view.tsx`: page UI.
- Create `frontend/app/risk-events/page.tsx`: page route.
- Create/update tests listed in each task.

---

### Task 1: Risk Taxonomy And Detector

**Files:**
- Create: `shared/procuresignal/risk_events/__init__.py`
- Create: `shared/procuresignal/risk_events/taxonomy.py`
- Create: `shared/procuresignal/risk_events/detector.py`
- Test: `tests/unit/test_risk_event_detector.py`

**Interfaces:**
- Consumes: `NewsArticleProcessed`, `NewsArticleRaw`, `canonical_signal_tag`, `expand_signal_terms`, `text_matches_signal_terms`, `canonical_region_name`, `extract_regions_from_text`.
- Produces:
  - `RiskEventCandidate`
  - `detect_risk_events(processed: NewsArticleProcessed, raw: NewsArticleRaw | None = None) -> list[RiskEventCandidate]`
  - `normalize_risk_type(value: str | None) -> str | None`
  - `risk_terms_for(values: Iterable[str] | None) -> set[str]`

- [ ] **Step 1: Write the failing detector tests**

Create `tests/unit/test_risk_event_detector.py` with:

```python
"""Tests for deterministic risk event detection."""

from datetime import datetime

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.risk_events.detector import detect_risk_events
from procuresignal.risk_events.taxonomy import normalize_risk_type, risk_terms_for


def _raw(**overrides) -> NewsArticleRaw:
    values = {
        "provider": "rss",
        "provider_article_id": "raw-1",
        "query_group": "supplier_risk",
        "ingest_hash": "raw-hash-1",
        "title": "LNG tanker attack threatens Qatar exports through Hormuz",
        "description": "Energy buyers are reviewing Middle East shipping risk.",
        "content_snippet": "The attack may disrupt supply chains in the Gulf.",
        "article_url": "https://example.com/risk",
        "source_name": "Reuters",
        "published_at": datetime.utcnow(),
        "ingested_at": datetime.utcnow(),
    }
    values.update(overrides)
    return NewsArticleRaw(**values)


def _processed(**overrides) -> NewsArticleProcessed:
    values = {
        "id": 77,
        "raw_article_id": 1,
        "normalized_title": "LNG tanker attack threatens Qatar exports through Hormuz",
        "summary": "Energy buyers are reviewing Middle East shipping risk after an attack.",
        "top_level_category": "energy",
        "signal_tags": [],
        "priority_signal": None,
        "detected_regions": [],
        "detected_suppliers": [],
        "detected_categories": ["energy"],
        "signal_score": 0.8,
        "processing_status": "completed",
        "llm_model": "openai/test",
        "language": "en",
        "processed_at": datetime.utcnow(),
    }
    values.update(overrides)
    return NewsArticleProcessed(**values)


def test_aliases_map_natural_terms_to_procurement_risks() -> None:
    assert normalize_risk_type("war") == "geopolitical"
    assert normalize_risk_type("middle east") == "regional_conflict"
    assert normalize_risk_type("supply chain") == "supply_disruption"
    assert "red sea" in risk_terms_for(["war"])


def test_detector_creates_geopolitical_event_with_evidence() -> None:
    events = detect_risk_events(_processed(), _raw())

    assert len(events) == 1
    event = events[0]
    assert event.risk_type in {"geopolitical", "regional_conflict"}
    assert event.severity in {"high", "critical"}
    assert event.confidence >= 0.7
    assert "Qatar" in event.affected_locations
    assert "energy" in event.affected_categories
    assert "attack" in event.evidence_snippet.lower()
    assert "Review supplier exposure" in event.recommendation


def test_detector_uses_existing_signal_tags() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="New import duty raises cost pressure",
            summary="Procurement teams are reviewing new customs duties.",
            signal_tags=["tariff"],
            priority_signal="tariff",
            detected_regions=["Germany"],
        ),
        _raw(title="New import duty raises cost pressure"),
    )

    assert [event.risk_type for event in events] == ["tariff"]
    assert events[0].affected_locations == ["Germany"]
    assert events[0].confidence >= 0.75


def test_detector_returns_empty_list_for_non_procurement_article() -> None:
    events = detect_risk_events(
        _processed(
            normalized_title="Markets move slightly after earnings",
            summary="Investors watched technology stocks during a quiet session.",
            signal_tags=[],
            priority_signal=None,
            detected_regions=[],
        ),
        _raw(title="Markets move slightly after earnings", description="A quiet session."),
    )

    assert events == []
```

- [ ] **Step 2: Run the failing detector tests**

Run:

```bash
poetry run pytest tests/unit/test_risk_event_detector.py -q
```

Expected: FAIL because `procuresignal.risk_events` does not exist.

- [ ] **Step 3: Create package exports**

Create `shared/procuresignal/risk_events/__init__.py`:

```python
"""Risk event detection and persistence."""

from .detector import RiskEventCandidate, detect_risk_events
from .taxonomy import normalize_risk_type, risk_terms_for

__all__ = [
    "RiskEventCandidate",
    "detect_risk_events",
    "normalize_risk_type",
    "risk_terms_for",
]
```

- [ ] **Step 4: Implement the taxonomy**

Create `shared/procuresignal/risk_events/taxonomy.py`:

```python
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
        normalized = normalize_signal_term(value)
        risk_type = _ALIAS_TO_TYPE.get(normalized, normalized)
        aliases = RISK_ALIASES.get(risk_type, {normalized})
        terms.update(expand_signal_terms([risk_type, *aliases]))
    return {term for term in terms if term}
```

- [ ] **Step 5: Implement the detector**

Create `shared/procuresignal/risk_events/detector.py`:

```python
"""Rule-based risk event detector."""

from __future__ import annotations

from dataclasses import dataclass

from procuresignal.enrichment.entities import canonical_region_name, extract_regions_from_text
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.signals.taxonomy import text_matches_signal_terms

from .taxonomy import RECOMMENDATIONS, RISK_TYPE_ORDER, SEVERITY_BY_RISK_TYPE, risk_terms_for


@dataclass(frozen=True)
class RiskEventCandidate:
    risk_type: str
    severity: str
    confidence: float
    affected_suppliers: list[str]
    affected_locations: list[str]
    affected_categories: list[str]
    evidence_snippet: str
    recommendation: str


def detect_risk_events(
    processed: NewsArticleProcessed,
    raw: NewsArticleRaw | None = None,
) -> list[RiskEventCandidate]:
    """Detect procurement risk events from one processed article."""

    text = _article_text(processed, raw)
    signal_values = [processed.priority_signal, *(processed.signal_tags or [])]
    article_signal_terms = risk_terms_for(signal_values)
    events: list[RiskEventCandidate] = []

    for risk_type in RISK_TYPE_ORDER:
        terms = risk_terms_for([risk_type])
        metadata_match = bool(article_signal_terms & terms)
        text_match = text_matches_signal_terms(text, terms)
        if not metadata_match and not text_match:
            continue

        confidence = _confidence(metadata_match, text_match, processed)
        if confidence < 0.55:
            continue

        events.append(
            RiskEventCandidate(
                risk_type=risk_type,
                severity=_severity(risk_type, text),
                confidence=confidence,
                affected_suppliers=_dedupe(processed.detected_suppliers or []),
                affected_locations=_locations(processed, text),
                affected_categories=_dedupe(
                    [processed.top_level_category, *(processed.detected_categories or [])]
                ),
                evidence_snippet=_evidence(text, terms),
                recommendation=RECOMMENDATIONS[risk_type],
            )
        )

    return _dedupe_events(events)


def _article_text(processed: NewsArticleProcessed, raw: NewsArticleRaw | None) -> str:
    parts = [
        processed.normalized_title,
        processed.summary,
        raw.title if raw else "",
        raw.description if raw else "",
        raw.content_snippet if raw else "",
        " ".join(processed.detected_regions or []),
        " ".join(processed.detected_categories or []),
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _confidence(
    metadata_match: bool,
    text_match: bool,
    processed: NewsArticleProcessed,
) -> float:
    score = 0.45
    if metadata_match:
        score += 0.25
    if text_match:
        score += 0.2
    if processed.priority_signal:
        score += 0.05
    if processed.detected_suppliers:
        score += 0.03
    if processed.detected_regions:
        score += 0.02
    return min(score, 0.95)


def _severity(risk_type: str, text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("bankruptcy", "missile", "shutdown", "embargo")):
        return "critical" if risk_type in {"bankruptcy", "geopolitical", "sanctions"} else "high"
    return SEVERITY_BY_RISK_TYPE[risk_type]


def _locations(processed: NewsArticleProcessed, text: str) -> list[str]:
    detected = list(processed.detected_regions or [])
    detected.extend(extract_regions_from_text(text))
    return _dedupe(canonical_region_name(value) for value in detected)


def _evidence(text: str, terms: set[str]) -> str:
    lowered = text.lower()
    match_positions = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
    if not match_positions:
        return text[:260].strip()
    center = min(match_positions)
    start = max(0, center - 90)
    end = min(len(text), center + 170)
    return text[start:end].strip()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _dedupe_events(events: list[RiskEventCandidate]) -> list[RiskEventCandidate]:
    by_type: dict[str, RiskEventCandidate] = {}
    for event in events:
        current = by_type.get(event.risk_type)
        if current is None or event.confidence > current.confidence:
            by_type[event.risk_type] = event
    return list(by_type.values())
```

- [ ] **Step 6: Run detector tests**

Run:

```bash
poetry run pytest tests/unit/test_risk_event_detector.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add shared/procuresignal/risk_events tests/unit/test_risk_event_detector.py
git commit -m "Add deterministic risk event detection"
```

---

### Task 2: Risk Event Model And Migration

**Files:**
- Create: `shared/procuresignal/models/risk_events.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Create: `migrations/versions/d4e5f6_add_risk_events.py`
- Modify: `tests/unit/test_models.py`

**Interfaces:**
- Consumes: `BaseModel`.
- Produces: `RiskEvent` SQLAlchemy model exported from `procuresignal.models`.

- [ ] **Step 1: Add failing model test**

Append to `tests/unit/test_models.py`:

```python
from shared.procuresignal.models import RiskEvent


@pytest.mark.asyncio
async def test_create_risk_event(async_session: AsyncSession) -> None:
    """Test creating an idempotent risk event."""

    event = RiskEvent(
        event_key="article-1:tariff:germany",
        processed_article_id=1,
        risk_type="tariff",
        severity="medium",
        confidence=0.82,
        affected_suppliers=["Bosch"],
        affected_locations=["Germany"],
        affected_categories=["automotive"],
        evidence_snippet="New import duty raises landed cost exposure.",
        recommendation="Check landed cost and tariff exposure before confirming new purchase orders.",
        source_name="Reuters",
        source_url="https://example.com",
        published_at=datetime.utcnow(),
        status="new",
    )

    async_session.add(event)
    await async_session.commit()

    assert event.id is not None
    assert event.event_key == "article-1:tariff:germany"
    assert event.affected_suppliers == ["Bosch"]
```

- [ ] **Step 2: Run failing model test**

Run:

```bash
poetry run pytest tests/unit/test_models.py::test_create_risk_event -q
```

Expected: FAIL because `RiskEvent` is not exported.

- [ ] **Step 3: Create the model**

Create `shared/procuresignal/models/risk_events.py`:

```python
"""Risk event models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class RiskEvent(BaseModel):
    """A procurement risk detected from a processed article."""

    __tablename__ = "risk_events"

    event_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    processed_article_id: Mapped[int] = mapped_column(nullable=False)

    risk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    affected_suppliers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_locations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    affected_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    evidence_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)

    __table_args__ = (
        UniqueConstraint("event_key", name="uq_risk_events_event_key"),
        Index("idx_risk_events_processed_article_id", "processed_article_id"),
        Index("idx_risk_events_type_status", "risk_type", "status"),
        Index("idx_risk_events_severity", "severity"),
        Index("idx_risk_events_published_at", "published_at"),
    )
```

- [ ] **Step 4: Export the model**

Modify `shared/procuresignal/models/__init__.py`:

```python
from .risk_events import RiskEvent
```

Add `"RiskEvent"` to `__all__`.

- [ ] **Step 5: Create migration**

Create `migrations/versions/d4e5f6_add_risk_events.py`:

```python
"""add risk events

Revision ID: d4e5f6_add_risk_events
Revises: c3d4e5_add_platform_language
Create Date: 2026-07-12 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6_add_risk_events"
down_revision = "c3d4e5_add_platform_language"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "risk_events",
        sa.Column("event_key", sa.String(length=500), nullable=False),
        sa.Column("processed_article_id", sa.Integer(), nullable=False),
        sa.Column("risk_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("affected_suppliers", sa.JSON(), nullable=False),
        sa.Column("affected_locations", sa.JSON(), nullable=False),
        sa.Column("affected_categories", sa.JSON(), nullable=False),
        sa.Column("evidence_snippet", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_risk_events_event_key"),
    )
    op.create_index("idx_risk_events_processed_article_id", "risk_events", ["processed_article_id"])
    op.create_index("idx_risk_events_type_status", "risk_events", ["risk_type", "status"])
    op.create_index("idx_risk_events_severity", "risk_events", ["severity"])
    op.create_index("idx_risk_events_published_at", "risk_events", ["published_at"])


def downgrade():
    op.drop_index("idx_risk_events_published_at", table_name="risk_events")
    op.drop_index("idx_risk_events_severity", table_name="risk_events")
    op.drop_index("idx_risk_events_type_status", table_name="risk_events")
    op.drop_index("idx_risk_events_processed_article_id", table_name="risk_events")
    op.drop_table("risk_events")
```

- [ ] **Step 6: Run model tests**

Run:

```bash
poetry run pytest tests/unit/test_models.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add shared/procuresignal/models/risk_events.py shared/procuresignal/models/__init__.py migrations/versions/d4e5f6_add_risk_events.py tests/unit/test_models.py
git commit -m "Store detected procurement risk events"
```

---

### Task 3: Idempotent Risk Event Persistence

**Files:**
- Create: `shared/procuresignal/risk_events/persistence.py`
- Test: `tests/unit/test_risk_event_persistence.py`

**Interfaces:**
- Consumes: `RiskEvent`, `NewsArticleProcessed`, `NewsArticleRaw`, `detect_risk_events`.
- Produces:
  - `RiskEventGenerationResult(created: int, updated: int, scanned: int, errors: int)`
  - `build_event_key(processed_article_id: int, risk_type: str, suppliers: list[str], locations: list[str]) -> str`
  - `generate_risk_events(session: AsyncSession, days_back: int = 7, limit: int = 500) -> RiskEventGenerationResult`

- [ ] **Step 1: Write failing persistence tests**

Create `tests/unit/test_risk_event_persistence.py` with:

```python
"""Tests for risk event persistence."""

from datetime import datetime

import pytest
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw, RiskEvent
from procuresignal.risk_events.persistence import build_event_key, generate_risk_events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def risk_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_article(session: AsyncSession) -> None:
    raw = NewsArticleRaw(
        provider="rss",
        provider_article_id="risk-1",
        query_group="supplier_risk",
        ingest_hash="risk-hash-1",
        title="LNG tanker attack threatens Qatar exports through Hormuz",
        description="Energy buyers are reviewing Middle East shipping risk.",
        content_snippet="The attack may disrupt supply chain flows in the Gulf.",
        article_url="https://example.com/risk",
        source_name="Reuters",
        published_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
    )
    session.add(raw)
    await session.flush()
    session.add(
        NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=raw.title,
            summary="Energy buyers are reviewing Middle East shipping risk after an attack.",
            top_level_category="energy",
            signal_tags=[],
            priority_signal=None,
            detected_regions=["Qatar"],
            detected_suppliers=[],
            detected_categories=["energy"],
            signal_score=0.8,
            processing_status="completed",
            llm_model="openai/test",
            language="en",
            processed_at=datetime.utcnow(),
        )
    )
    await session.commit()


def test_build_event_key_is_stable() -> None:
    first = build_event_key(1, "tariff", ["Bosch"], ["Germany", "Poland"])
    second = build_event_key(1, "tariff", ["bosch"], ["poland", "germany"])

    assert first == second


@pytest.mark.asyncio
async def test_generate_risk_events_is_idempotent(risk_session: AsyncSession) -> None:
    await _seed_article(risk_session)

    first = await generate_risk_events(risk_session, days_back=7, limit=50)
    second = await generate_risk_events(risk_session, days_back=7, limit=50)
    result = await risk_session.execute(select(RiskEvent))
    events = result.scalars().all()

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1
    assert len(events) == 1
    assert events[0].risk_type in {"geopolitical", "regional_conflict"}
```

- [ ] **Step 2: Run failing persistence tests**

Run:

```bash
poetry run pytest tests/unit/test_risk_event_persistence.py -q
```

Expected: FAIL because `procuresignal.risk_events.persistence` does not exist.

- [ ] **Step 3: Implement persistence**

Create `shared/procuresignal/risk_events/persistence.py`:

```python
"""Persistence helpers for detected risk events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, RiskEvent
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .detector import RiskEventCandidate, detect_risk_events


@dataclass(frozen=True)
class RiskEventGenerationResult:
    created: int
    updated: int
    scanned: int
    errors: int


def build_event_key(
    processed_article_id: int,
    risk_type: str,
    suppliers: list[str],
    locations: list[str],
) -> str:
    """Build a deterministic idempotency key for a risk event."""

    supplier_part = ",".join(sorted({value.strip().lower() for value in suppliers if value.strip()}))
    location_part = ",".join(sorted({value.strip().lower() for value in locations if value.strip()}))
    digest = sha256(f"{processed_article_id}:{risk_type}:{supplier_part}:{location_part}".encode()).hexdigest()
    return digest[:40]


async def generate_risk_events(
    session: AsyncSession,
    days_back: int = 7,
    limit: int = 500,
) -> RiskEventGenerationResult:
    """Generate or update risk events from recent processed articles."""

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    result = await session.execute(
        select(NewsArticleProcessed, NewsArticleRaw)
        .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
        .where(NewsArticleProcessed.processed_at >= cutoff)
        .order_by(desc(NewsArticleProcessed.processed_at))
        .limit(limit)
    )
    rows = result.all()
    created = 0
    updated = 0
    errors = 0

    for processed, raw in rows:
        try:
            for candidate in detect_risk_events(processed, raw):
                was_created = await _upsert_event(session, processed, raw, candidate)
                if was_created:
                    created += 1
                else:
                    updated += 1
        except Exception:
            errors += 1

    await session.commit()
    return RiskEventGenerationResult(created=created, updated=updated, scanned=len(rows), errors=errors)


async def _upsert_event(
    session: AsyncSession,
    processed: NewsArticleProcessed,
    raw: NewsArticleRaw,
    candidate: RiskEventCandidate,
) -> bool:
    event_key = build_event_key(
        processed.id,
        candidate.risk_type,
        candidate.affected_suppliers,
        candidate.affected_locations,
    )
    existing = await session.scalar(select(RiskEvent).where(RiskEvent.event_key == event_key))
    if existing:
        existing.severity = candidate.severity
        existing.confidence = candidate.confidence
        existing.affected_suppliers = candidate.affected_suppliers
        existing.affected_locations = candidate.affected_locations
        existing.affected_categories = candidate.affected_categories
        existing.evidence_snippet = candidate.evidence_snippet
        existing.recommendation = candidate.recommendation
        existing.source_name = raw.source_name
        existing.source_url = raw.article_url
        existing.published_at = raw.published_at
        return False

    session.add(
        RiskEvent(
            event_key=event_key,
            processed_article_id=processed.id,
            risk_type=candidate.risk_type,
            severity=candidate.severity,
            confidence=candidate.confidence,
            affected_suppliers=candidate.affected_suppliers,
            affected_locations=candidate.affected_locations,
            affected_categories=candidate.affected_categories,
            evidence_snippet=candidate.evidence_snippet,
            recommendation=candidate.recommendation,
            source_name=raw.source_name,
            source_url=raw.article_url,
            published_at=raw.published_at,
            status="new",
        )
    )
    return True
```

- [ ] **Step 4: Run persistence tests**

Run:

```bash
poetry run pytest tests/unit/test_risk_event_persistence.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add shared/procuresignal/risk_events/persistence.py tests/unit/test_risk_event_persistence.py
git commit -m "Generate risk events idempotently"
```

---

### Task 4: Risk Events API

**Files:**
- Create: `api/schemas/risk_event.py`
- Create: `api/routers/risk_events.py`
- Modify: `api/main.py`
- Modify: `api/translation.py`
- Modify: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `RiskEvent`, `UserNewsPreference`, `PreferenceMatcher`, `generate_risk_events`.
- Produces:
  - `GET /api/risk-events`
  - `GET /api/risk-events/{risk_event_id}`
  - `PATCH /api/risk-events/{risk_event_id}/status`
  - `translate_risk_events(events: list[RiskEventItem], language: str | None) -> list[RiskEventItem]`

- [ ] **Step 1: Add failing API tests**

Append to `tests/integration/test_api.py`:

```python
from procuresignal.models import RiskEvent


def test_risk_events_endpoint_generates_and_lists_events(api_client: TestClient) -> None:
    response = api_client.get("/api/risk-events", params={"user_id": "user-123", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-123"
    assert payload["total_count"] >= 0
    assert "events" in payload


def test_risk_event_status_update(api_client: TestClient) -> None:
    created = api_client.get("/api/risk-events", params={"user_id": "user-123", "limit": 20})
    assert created.status_code == 200
    events = created.json()["events"]
    if not events:
        pytest.skip("seed data did not produce a risk event")

    event_id = events[0]["id"]
    response = api_client.patch(f"/api/risk-events/{event_id}/status", json={"status": "reviewed"})

    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"
```

Also change the seeded `processed_missing_entities` article in the existing fixture so it can generate a risk event:

```python
processed_missing_entities = NewsArticleProcessed(
    raw_article_id=raw_missing_entities.id,
    normalized_title="Ferrari supplier talks expand in Italy after strike warning",
    summary="Ferrari and Mercedes are watching supplier continuity in Italy after strike disruption.",
    top_level_category="automotive",
    signal_tags=["strike", "supplier_risk"],
    priority_signal="strike",
    detected_regions=[],
    detected_suppliers=[],
    detected_categories=[],
    signal_score=0.71,
    processing_status="completed",
    llm_model="openai/test-model",
    language="en",
    processed_at=datetime.utcnow(),
)
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
poetry run pytest tests/integration/test_api.py::test_risk_events_endpoint_generates_and_lists_events tests/integration/test_api.py::test_risk_event_status_update -q
```

Expected: FAIL because `/api/risk-events` is not registered.

- [ ] **Step 3: Add schemas**

Create `api/schemas/risk_event.py`:

```python
"""Risk event API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskEventStatus = Literal["new", "reviewed", "dismissed"]


class RiskEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    processed_article_id: int
    risk_type: str
    severity: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    affected_suppliers: list[str] = Field(default_factory=list)
    affected_locations: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    evidence_snippet: str
    recommendation: str
    source_name: str
    source_url: str | None = None
    published_at: datetime
    status: RiskEventStatus
    rank_score: float = Field(..., ge=0.0, le=1.0)


class RiskEventResponse(BaseModel):
    user_id: str
    events: list[RiskEventItem]
    total_count: int = Field(..., ge=0)
    generated_at: datetime


class RiskEventStatusUpdate(BaseModel):
    status: RiskEventStatus
```

- [ ] **Step 4: Add translation support**

Modify `api/translation.py`:

```python
from api.schemas.risk_event import RiskEventItem
```

Add:

```python
_RISK_EVENT_FIELDS = ("evidence_snippet", "recommendation")
```

Add:

```python
async def translate_risk_events(
    events: list[RiskEventItem],
    language: str | None,
) -> list[RiskEventItem]:
    """Translate user-facing risk event text for non-English users."""

    return await _translate_models(events, language, _RISK_EVENT_FIELDS, "risk-event")
```

Update `ArticleModel` to:

```python
ArticleModel = TypeVar("ArticleModel", ArticleInFeed, ArticleDetail, SearchResult, RiskEventItem)
```

- [ ] **Step 5: Add router**

Create `api/routers/risk_events.py`:

```python
"""Risk event endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import RiskEvent, UserNewsPreference
from procuresignal.personalization.matcher import PreferenceMatcher
from procuresignal.risk_events.persistence import generate_risk_events
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.risk_event import RiskEventItem, RiskEventResponse, RiskEventStatusUpdate
from api.translation import translate_risk_events

router = APIRouter(prefix="/api/risk-events", tags=["risk-events"])


@router.get("", response_model=RiskEventResponse)
async def list_risk_events(
    user_id: str = Query(..., min_length=1, max_length=100),
    risk_type: str | None = Query(None),
    severity: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    supplier: str | None = Query(None),
    location: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> RiskEventResponse:
    """List procurement risk events."""

    await generate_risk_events(session, days_back=7, limit=500)
    stmt = select(RiskEvent)
    stmt = _apply_filters(stmt, risk_type, severity, status_filter)
    result = await session.execute(stmt.order_by(desc(RiskEvent.published_at)).limit(limit + offset))
    all_events = list(result.scalars().all())

    preference = await session.scalar(
        select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
    )
    filtered = [
        event
        for event in all_events
        if _contains(event.affected_suppliers, supplier)
        and _contains(event.affected_locations, location)
        and _contains(event.affected_categories, category)
    ]
    ranked = sorted(filtered, key=lambda event: _rank_score(event, preference), reverse=True)
    page = ranked[offset : offset + limit]
    items = [_to_item(event, _rank_score(event, preference)) for event in page]
    items = await translate_risk_events(items, language)

    return RiskEventResponse(
        user_id=user_id,
        events=items,
        total_count=len(ranked),
        generated_at=datetime.utcnow(),
    )


@router.get("/{risk_event_id}", response_model=RiskEventItem)
async def get_risk_event(
    risk_event_id: int,
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> RiskEventItem:
    event = await session.get(RiskEvent, risk_event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk event not found")
    translated = await translate_risk_events([_to_item(event, event.confidence)], language)
    return translated[0]


@router.patch("/{risk_event_id}/status", response_model=RiskEventItem)
async def update_risk_event_status(
    risk_event_id: int,
    payload: RiskEventStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> RiskEventItem:
    event = await session.get(RiskEvent, risk_event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk event not found")
    event.status = payload.status
    await session.commit()
    await session.refresh(event)
    return _to_item(event, event.confidence)


def _apply_filters(stmt, risk_type, severity, status_filter):
    if risk_type:
        stmt = stmt.where(RiskEvent.risk_type == risk_type)
    if severity:
        stmt = stmt.where(RiskEvent.severity == severity)
    if status_filter:
        stmt = stmt.where(RiskEvent.status == status_filter)
    return stmt


def _contains(values: list[str], expected: str | None) -> bool:
    if not expected:
        return True
    expected_lower = expected.strip().lower()
    return any(expected_lower in value.lower() for value in values)


def _rank_score(event: RiskEvent, preference: UserNewsPreference | None) -> float:
    if preference is None:
        return event.confidence
    score = event.confidence
    if PreferenceMatcher._normalized(event.affected_suppliers) & PreferenceMatcher._preferred_suppliers(preference):
        score += 0.15
    if PreferenceMatcher._region_tokens(event.affected_locations) & PreferenceMatcher._preferred_regions(preference):
        score += 0.15
    if set(event.affected_categories or []) & PreferenceMatcher._preferred_categories(preference):
        score += 0.1
    if event.risk_type in {value.replace(" ", "_") for value in PreferenceMatcher._preferred_signals(preference)}:
        score += 0.1
    return min(score, 1.0)


def _to_item(event: RiskEvent, rank_score: float) -> RiskEventItem:
    return RiskEventItem(
        id=event.id,
        processed_article_id=event.processed_article_id,
        risk_type=event.risk_type,
        severity=event.severity,
        confidence=event.confidence,
        affected_suppliers=event.affected_suppliers or [],
        affected_locations=event.affected_locations or [],
        affected_categories=event.affected_categories or [],
        evidence_snippet=event.evidence_snippet,
        recommendation=event.recommendation,
        source_name=event.source_name,
        source_url=event.source_url,
        published_at=event.published_at,
        status=event.status,
        rank_score=rank_score,
    )
```

- [ ] **Step 6: Register router**

Modify `api/main.py` imports:

```python
from api.routers import articles, chat, currency, feed, health, preferences, risk_events, signals
```

Add after feed router:

```python
app.include_router(risk_events.router)
```

- [ ] **Step 7: Run API tests**

Run:

```bash
poetry run pytest tests/integration/test_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add api/schemas/risk_event.py api/routers/risk_events.py api/main.py api/translation.py tests/integration/test_api.py
git commit -m "Expose risk events through the API"
```

---

### Task 5: Scheduled Risk Event Generation

**Files:**
- Modify: `worker/tasks.py`
- Modify: `worker/celery_config.py`
- Modify: `api/scheduler.py`
- Test: `tests/unit/test_scheduler.py`
- Test: `tests/unit/test_tasks.py`

**Interfaces:**
- Consumes: `generate_risk_events`.
- Produces: `worker.tasks.generate_risk_events_task`.

- [ ] **Step 1: Add failing task and scheduler tests**

Append to `tests/unit/test_tasks.py`:

```python
def test_generate_risk_events_task_is_exported() -> None:
    from worker.tasks import __all__

    assert "generate_risk_events_task" in __all__
```

Append to `tests/unit/test_scheduler.py`:

```python
def test_scheduler_registers_risk_event_job() -> None:
    from api.scheduler import SCHEDULED_JOB_IDS

    assert "generate-risk-events" in SCHEDULED_JOB_IDS
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
poetry run pytest tests/unit/test_tasks.py::test_generate_risk_events_task_is_exported tests/unit/test_scheduler.py::test_scheduler_registers_risk_event_job -q
```

Expected: FAIL because task/job is missing.

- [ ] **Step 3: Add Celery task**

Modify `worker/tasks.py` imports:

```python
from procuresignal.risk_events.persistence import generate_risk_events
```

Add before `health_check_task`:

```python
@app.task(
    name="worker.tasks.generate_risk_events_task",
    bind=True,
    max_retries=2,
    queue="personalization",
    time_limit=1800,
)
def generate_risk_events_task(self) -> dict[str, Any]:
    """Generate idempotent procurement risk events from processed articles."""

    async def _run() -> dict[str, Any]:
        async with session_scope() as session:
            result = await generate_risk_events(session, days_back=7, limit=500)
            return {
                "status": "success",
                "created": result.created,
                "updated": result.updated,
                "scanned": result.scanned,
                "errors": result.errors,
                "timestamp": datetime.utcnow().isoformat(),
            }

    return _run_with_retry(self, _run)
```

Add to `__all__`:

```python
"generate_risk_events_task",
```

- [ ] **Step 4: Add Celery routing and beat schedule**

Modify `worker/celery_config.py` `CELERY_TASK_ROUTES`:

```python
"worker.tasks.generate_risk_events_task": {
    "queue": "personalization",
    "routing_key": "personalization",
},
```

Add to `CELERY_BEAT_SCHEDULE`:

```python
"generate-risk-events-hourly": {
    "task": "worker.tasks.generate_risk_events_task",
    "schedule": crontab(minute=50, hour="*"),
    "options": {"queue": "personalization"},
},
```

- [ ] **Step 5: Add APScheduler job**

Modify `api/scheduler.py`:

```python
SCHEDULED_JOB_IDS = (
    "retrieve-news",
    "normalize-articles",
    "enrich-articles",
    "generate-risk-events",
    "personalize-feeds",
    "prune-retention",
)
```

Add:

```python
def _enqueue_generate_risk_events() -> None:
    from worker.tasks import generate_risk_events_task

    generate_risk_events_task.delay()
```

Add in `configure_scheduler` after enrichment:

```python
scheduler.add_job(
    _enqueue_generate_risk_events,
    "cron",
    minute=50,
    hour="*/2",
    **_job_options("generate-risk-events"),
)
```

- [ ] **Step 6: Run task and scheduler tests**

Run:

```bash
poetry run pytest tests/unit/test_tasks.py tests/unit/test_scheduler.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add worker/tasks.py worker/celery_config.py api/scheduler.py tests/unit/test_tasks.py tests/unit/test_scheduler.py
git commit -m "Schedule procurement risk event generation"
```

---

### Task 6: Frontend Risk Events Page

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/i18n.ts`
- Modify: `frontend/components/header.tsx`
- Create: `frontend/components/risk-events-view.tsx`
- Create: `frontend/app/risk-events/page.tsx`
- Test: `frontend/__tests__/api.test.ts`
- Test: `frontend/__tests__/header.test.tsx`
- Create: `frontend/__tests__/risk-events-view.test.tsx`

**Interfaces:**
- Consumes: `GET /api/risk-events`, `PATCH /api/risk-events/{id}/status`.
- Produces:
  - `getRiskEvents(userId: string, opts?: { limit?: number; language?: string })`
  - `updateRiskEventStatus(id: number, status: RiskEventStatus)`
  - `RiskEventsView`

- [ ] **Step 1: Add failing frontend API tests**

Append to `frontend/__tests__/api.test.ts`:

```typescript
it("getRiskEvents calls /api/risk-events with user_id and language", async () => {
  mockedGet.mockResolvedValue({ data: { user_id: "u1", events: [], total_count: 0 } });
  const res = await api.getRiskEvents("u1", { limit: 25, language: "de" });
  expect(mockedGet).toHaveBeenCalledWith("/api/risk-events", {
    params: { user_id: "u1", limit: 25, language: "de" },
  });
  expect(res.user_id).toBe("u1");
});

it("updateRiskEventStatus patches status", async () => {
  mockedPatch.mockResolvedValue({ data: { id: 1, status: "reviewed" } });
  const res = await api.updateRiskEventStatus(1, "reviewed");
  expect(mockedPatch).toHaveBeenCalledWith("/api/risk-events/1/status", {
    status: "reviewed",
  });
  expect(res.status).toBe("reviewed");
});
```

- [ ] **Step 2: Add failing view test**

Create `frontend/__tests__/risk-events-view.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getRiskEvents: vi.fn(),
  updateRiskEventStatus: vi.fn(),
}));

import * as api from "@/lib/api";
import { RiskEventsView } from "@/components/risk-events-view";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "buyer@example.com", platformLanguage: "en" });
  vi.mocked(api.getRiskEvents).mockResolvedValue({
    user_id: "buyer@example.com",
    total_count: 1,
    generated_at: "2026-07-12T10:00:00Z",
    events: [
      {
        id: 1,
        processed_article_id: 7,
        risk_type: "geopolitical",
        severity: "high",
        confidence: 0.82,
        affected_suppliers: [],
        affected_locations: ["Qatar"],
        affected_categories: ["energy"],
        evidence_snippet: "LNG tanker attack threatens Qatar exports.",
        recommendation: "Review supplier exposure in this region before placing large orders.",
        source_name: "Reuters",
        source_url: "https://example.com/risk",
        published_at: "2026-07-12T08:00:00Z",
        status: "new",
        rank_score: 0.9,
      },
    ],
  });
  vi.mocked(api.updateRiskEventStatus).mockResolvedValue({
    id: 1,
    processed_article_id: 7,
    risk_type: "geopolitical",
    severity: "high",
    confidence: 0.82,
    affected_suppliers: [],
    affected_locations: ["Qatar"],
    affected_categories: ["energy"],
    evidence_snippet: "LNG tanker attack threatens Qatar exports.",
    recommendation: "Review supplier exposure in this region before placing large orders.",
    source_name: "Reuters",
    source_url: "https://example.com/risk",
    published_at: "2026-07-12T08:00:00Z",
    status: "reviewed",
    rank_score: 0.9,
  });
});

describe("RiskEventsView", () => {
  it("renders risk events with a clean percentage", async () => {
    render(<RiskEventsView />);
    await waitFor(() => expect(screen.getByText("Geopolitical")).toBeInTheDocument());
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.queryByText(/match/i)).not.toBeInTheDocument();
    expect(api.getRiskEvents).toHaveBeenCalledWith("buyer@example.com", {
      language: "en",
      limit: 50,
    });
  });

  it("updates status", async () => {
    render(<RiskEventsView />);
    await waitFor(() => expect(screen.getByText("Geopolitical")).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Status for risk event 1"), "reviewed");
    expect(api.updateRiskEventStatus).toHaveBeenCalledWith(1, "reviewed");
  });
});
```

- [ ] **Step 3: Run failing frontend tests**

Run:

```bash
cd frontend
npm run test:run -- api.test.ts risk-events-view.test.tsx header.test.tsx
```

Expected: FAIL because risk event functions and component do not exist.

- [ ] **Step 4: Add TypeScript types**

Modify `frontend/lib/types.ts`:

```typescript
export type RiskEventStatus = "new" | "reviewed" | "dismissed";

export interface RiskEvent {
  id: number;
  processed_article_id: number;
  risk_type: string;
  severity: string;
  confidence: number;
  affected_suppliers: string[];
  affected_locations: string[];
  affected_categories: string[];
  evidence_snippet: string;
  recommendation: string;
  source_name: string;
  source_url: string | null;
  published_at: string;
  status: RiskEventStatus;
  rank_score: number;
}

export interface RiskEventResponse {
  user_id: string;
  events: RiskEvent[];
  total_count: number;
  generated_at: string;
}
```

- [ ] **Step 5: Add API client functions**

Modify imports in `frontend/lib/api.ts`:

```typescript
RiskEvent,
RiskEventResponse,
RiskEventStatus,
```

Add:

```typescript
export async function getRiskEvents(
  userId: string,
  opts: { limit?: number; language?: string } = {},
): Promise<RiskEventResponse> {
  const { data } = await client.get("/api/risk-events", {
    params: {
      user_id: userId,
      limit: opts.limit ?? 50,
      language: opts.language ?? "en",
    },
  });
  return data;
}

export async function updateRiskEventStatus(
  id: number,
  status: RiskEventStatus,
): Promise<RiskEvent> {
  const { data } = await client.patch(`/api/risk-events/${id}/status`, { status });
  return data;
}
```

- [ ] **Step 6: Add i18n labels**

Modify `frontend/lib/i18n.ts` `EN`:

```typescript
"nav.risks": "Risks",
"risks.eyebrow": "Procurement risk events",
"risks.title": "Risk Events",
"risks.subtitle": "Evidence-backed risks detected from your market intelligence feed.",
"risks.countMany": "{count} risks",
"risks.countOne": "1 risk",
"risks.loading": "Loading risk events...",
"risks.noEventsTitle": "No risk events yet",
"risks.noEventsHint": "Procurement risks will appear as matching articles are processed.",
"risks.unavailableTitle": "Risk events unavailable",
"risks.unavailableHint": "The risk event service did not respond. Retry when the API is available.",
"risks.evidence": "Evidence",
"risks.recommendation": "Recommended next step",
"risks.status": "Status",
"risks.new": "New",
"risks.reviewed": "Reviewed",
"risks.dismissed": "Dismissed",
```

Add these German values:

```typescript
"nav.risks": "Risiken",
"risks.eyebrow": "Beschaffungsrisiken",
"risks.title": "Risikoereignisse",
"risks.subtitle": "Evidenzbasierte Risiken aus Ihrem Marktintelligenz-Feed.",
"risks.countMany": "{count} Risiken",
"risks.countOne": "1 Risiko",
"risks.loading": "Risikoereignisse werden geladen...",
"risks.noEventsTitle": "Noch keine Risikoereignisse",
"risks.noEventsHint": "Beschaffungsrisiken erscheinen, sobald passende Artikel verarbeitet sind.",
"risks.unavailableTitle": "Risikoereignisse nicht verfuegbar",
"risks.unavailableHint": "Der Risikoereignis-Service hat nicht geantwortet. Versuchen Sie es erneut, wenn die API verfuegbar ist.",
"risks.evidence": "Nachweis",
"risks.recommendation": "Empfohlener naechster Schritt",
"risks.status": "Status",
"risks.new": "Neu",
"risks.reviewed": "Geprueft",
"risks.dismissed": "Ausgeblendet",
```

Add these French values:

```typescript
"nav.risks": "Risques",
"risks.eyebrow": "Risques achats",
"risks.title": "Evenements de risque",
"risks.subtitle": "Risques etayes par des preuves detectes dans votre flux de veille marche.",
"risks.countMany": "{count} risques",
"risks.countOne": "1 risque",
"risks.loading": "Chargement des risques...",
"risks.noEventsTitle": "Aucun risque pour le moment",
"risks.noEventsHint": "Les risques achats apparaitront lorsque les articles correspondants seront traites.",
"risks.unavailableTitle": "Risques indisponibles",
"risks.unavailableHint": "Le service de risques n'a pas repondu. Reessayez lorsque l'API est disponible.",
"risks.evidence": "Preuve",
"risks.recommendation": "Prochaine etape recommandee",
"risks.status": "Statut",
"risks.new": "Nouveau",
"risks.reviewed": "Verifie",
"risks.dismissed": "Ignore",
```

Add these Spanish values:

```typescript
"nav.risks": "Riesgos",
"risks.eyebrow": "Riesgos de compras",
"risks.title": "Eventos de riesgo",
"risks.subtitle": "Riesgos con evidencia detectados desde tu feed de inteligencia de mercado.",
"risks.countMany": "{count} riesgos",
"risks.countOne": "1 riesgo",
"risks.loading": "Cargando eventos de riesgo...",
"risks.noEventsTitle": "Aun no hay eventos de riesgo",
"risks.noEventsHint": "Los riesgos de compras apareceran cuando se procesen articulos coincidentes.",
"risks.unavailableTitle": "Eventos de riesgo no disponibles",
"risks.unavailableHint": "El servicio de riesgos no respondio. Reintenta cuando la API este disponible.",
"risks.evidence": "Evidencia",
"risks.recommendation": "Siguiente paso recomendado",
"risks.status": "Estado",
"risks.new": "Nuevo",
"risks.reviewed": "Revisado",
"risks.dismissed": "Descartado",
```

- [ ] **Step 7: Add nav item**

Modify `frontend/components/header.tsx` `NAV`:

```typescript
const NAV = [
  { href: "/", labelKey: "nav.feed" },
  { href: "/risk-events", labelKey: "nav.risks" },
  { href: "/preferences", labelKey: "nav.preferences" },
  { href: "/chat", labelKey: "nav.chat" },
] satisfies { href: string; labelKey: TranslationKey }[];
```

Update `frontend/__tests__/header.test.tsx`:

```typescript
expect(screen.getByRole("link", { name: "Risks" })).toBeInTheDocument();
```

- [ ] **Step 8: Create the view**

Create `frontend/components/risk-events-view.tsx`:

```typescript
"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { getRiskEvents, updateRiskEventStatus } from "@/lib/api";
import { t } from "@/lib/i18n";
import { formatDate, humanize } from "@/lib/labels";
import type { RiskEvent, RiskEventStatus } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useUserStore } from "@/store/user";

export function RiskEventsView() {
  const userId = useUserStore((s) => s.userId);
  const language = useUserStore((s) => s.platformLanguage);
  const risks = useApi(() => getRiskEvents(userId, { language, limit: 50 }), [userId, language]);
  const events = useMemo(() => risks.data?.events ?? [], [risks.data?.events]);

  return (
    <main className="space-y-5">
      <section className="flex flex-col gap-4 border-b border-slate-200 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">
            {t(language, "risks.eyebrow")}
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">
            {t(language, "risks.title")}
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
            {t(language, "risks.subtitle")}
          </p>
        </div>
        {events.length > 0 ? (
          <span className="text-sm font-medium text-slate-600">
            {t(language, events.length === 1 ? "risks.countOne" : "risks.countMany", {
              count: events.length,
            })}
          </span>
        ) : null}
      </section>

      <RiskEventList
        loading={risks.loading}
        error={risks.error}
        events={events}
        onRetry={risks.reload}
        language={language}
      />
    </main>
  );
}

function RiskEventList({
  loading,
  error,
  events,
  onRetry,
  language,
}: {
  loading: boolean;
  error: string | null;
  events: RiskEvent[];
  onRetry: () => void;
  language: string;
}) {
  if (loading) return <Spinner label={t(language, "risks.loading")} />;
  if (error) {
    return (
      <Card className="border-red-200 bg-red-50/70">
        <p className="text-sm font-semibold text-red-800">
          {t(language, "risks.unavailableTitle")}
        </p>
        <p className="mt-1 text-sm text-red-700">
          {t(language, "risks.unavailableHint")}
        </p>
        <Button className="mt-3" variant="secondary" onClick={onRetry}>
          {t(language, "common.retry")}
        </Button>
      </Card>
    );
  }
  if (events.length === 0) {
    return (
      <EmptyState title={t(language, "risks.noEventsTitle")} hint={t(language, "risks.noEventsHint")} />
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70">
      <div className="divide-y divide-slate-100">
        {events.map((event) => (
          <RiskEventRow key={event.id} event={event} language={language} />
        ))}
      </div>
    </div>
  );
}

function RiskEventRow({ event, language }: { event: RiskEvent; language: string }) {
  const [status, setStatus] = useState<RiskEventStatus>(event.status);
  const confidence = Math.round(event.confidence * 100);

  const changeStatus = async (nextStatus: RiskEventStatus) => {
    setStatus(nextStatus);
    try {
      await updateRiskEventStatus(event.id, nextStatus);
    } catch {
      setStatus(event.status);
    }
  };

  return (
    <article className="px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span className="font-semibold uppercase text-slate-600">
              {humanize(event.risk_type)}
            </span>
            <span aria-hidden>|</span>
            <span>{humanize(event.severity)}</span>
            <span aria-hidden>|</span>
            <span>{event.source_name}</span>
            <span aria-hidden>|</span>
            <span>{formatDate(event.published_at)}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-700">{event.evidence_snippet}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-sm font-semibold text-slate-950">{confidence}%</span>
          <select
            aria-label={`Status for risk event ${event.id}`}
            value={status}
            onChange={(e) => void changeStatus(e.target.value as RiskEventStatus)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700 shadow-sm"
          >
            <option value="new">{t(language, "risks.new")}</option>
            <option value="reviewed">{t(language, "risks.reviewed")}</option>
            <option value="dismissed">{t(language, "risks.dismissed")}</option>
          </select>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {event.affected_suppliers.length > 0 ? (
          <span>{t(language, "article.suppliers")}: {event.affected_suppliers.map(humanize).join(", ")}</span>
        ) : null}
        {event.affected_locations.length > 0 ? (
          <span>{t(language, "article.regions")}: {event.affected_locations.map(humanize).join(", ")}</span>
        ) : null}
      </div>
      <p className="mt-3 text-xs font-semibold uppercase text-slate-500">
        {t(language, "risks.recommendation")}
      </p>
      <p className="mt-1 text-sm leading-6 text-slate-700">{event.recommendation}</p>
    </article>
  );
}
```

- [ ] **Step 9: Add page route**

Create `frontend/app/risk-events/page.tsx`:

```typescript
import { RiskEventsView } from "@/components/risk-events-view";

export default function RiskEventsPage() {
  return <RiskEventsView />;
}
```

- [ ] **Step 10: Run frontend tests**

Run:

```bash
cd frontend
npm run test:run -- api.test.ts risk-events-view.test.tsx header.test.tsx
npm run typecheck
```

Expected: PASS.

- [ ] **Step 11: Commit Task 6**

Run:

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/lib/i18n.ts frontend/components/header.tsx frontend/components/risk-events-view.tsx frontend/app/risk-events/page.tsx frontend/__tests__/api.test.ts frontend/__tests__/header.test.tsx frontend/__tests__/risk-events-view.test.tsx
git commit -m "Add risk events experience"
```

---

### Task 7: Full Verification And Final Polish

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Consumes: completed Tasks 1-6.
- Produces: verified branch ready for user testing.

- [ ] **Step 1: Run backend unit/integration tests**

Run:

```bash
poetry run pytest tests/unit/test_risk_event_detector.py tests/unit/test_risk_event_persistence.py tests/unit/test_models.py tests/unit/test_tasks.py tests/unit/test_scheduler.py tests/integration/test_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests and checks**

Run:

```bash
cd frontend
npm run test:run
npm run typecheck
npm run lint
```

Expected: PASS.

- [ ] **Step 3: Run backend style checks**

Run:

```bash
poetry run ruff check api shared worker tests
poetry run black --check api shared worker tests
```

Expected: PASS.

- [ ] **Step 4: Verify no unwanted files are staged**

Run:

```bash
git status --short
```

Expected: only intentional source, test, migration, and docs files are tracked. Generated files such as `.coverage 2`, duplicate `* 2.py`, duplicate `* 2.tsx`, and stale `.next` directories must remain unstaged.

- [ ] **Step 5: Commit verification fixes if any**

If Step 1, 2, or 3 required source fixes, run:

```bash
git add -u
git commit -m "Polish risk event layer"
```

If no fixes were required, skip this commit.

- [ ] **Step 6: Report ready for app testing**

Provide the user:

```text
Risk event layer is implemented on codex/risk-event-layer-design.
Backend tests: passing.
Frontend tests/typecheck/lint: passing.
No generated local artifacts were committed.
```
