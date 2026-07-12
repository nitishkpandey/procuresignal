"""Persistence helpers for detected risk events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, RiskEvent

from .detector import RiskEventCandidate, detect_risk_events

logger = logging.getLogger(__name__)


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

    supplier_part = ",".join(
        sorted({value.strip().lower() for value in suppliers if value.strip()})
    )
    location_part = ",".join(
        sorted({value.strip().lower() for value in locations if value.strip()})
    )
    digest = sha256(
        f"{processed_article_id}:{risk_type}:{supplier_part}:{location_part}".encode()
    ).hexdigest()
    return digest[:40]


async def generate_risk_events(
    session: AsyncSession,
    days_back: int = 7,
    limit: int = 500,
) -> RiskEventGenerationResult:
    """Generate risk events from recently processed, unscanned articles."""

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    result = await session.execute(
        select(NewsArticleProcessed, NewsArticleRaw)
        .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
        .where(
            NewsArticleProcessed.processed_at >= cutoff,
            NewsArticleProcessed.risk_event_checked_at.is_(None),
        )
        .order_by(asc(NewsArticleProcessed.processed_at), asc(NewsArticleProcessed.id))
        .limit(limit)
    )
    rows = result.all()
    created = 0
    updated = 0
    errors = 0

    for processed, raw in rows:
        processed_article_id = processed.id
        try:
            article_created = 0
            article_updated = 0
            async with session.begin_nested():
                for candidate in detect_risk_events(processed, raw):
                    was_created = await _upsert_event(session, processed, raw, candidate)
                    if was_created:
                        article_created += 1
                    else:
                        article_updated += 1
                processed.risk_event_checked_at = datetime.utcnow()
                await session.flush()
        except Exception:
            logger.exception(
                "Failed to generate risk events for processed_article_id=%s", processed_article_id
            )
            errors += 1
        else:
            created += article_created
            updated += article_updated

    await session.commit()
    return RiskEventGenerationResult(
        created=created,
        updated=updated,
        scanned=len(rows),
        errors=errors,
    )


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
