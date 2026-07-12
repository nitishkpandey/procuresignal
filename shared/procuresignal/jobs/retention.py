"""Retention jobs for news storage tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, RiskEvent, UserNewsFeed


@dataclass(slots=True)
class RetentionPolicy:
    raw_days: int = 14
    processed_days: int = 30
    feed_days: int = 14
    risk_event_days: int = 14


@dataclass(slots=True)
class RetentionResult:
    raw_deleted: int
    processed_deleted: int
    feed_deleted: int
    risk_events_deleted: int


async def prune_expired_records(
    session: AsyncSession,
    *,
    policy: RetentionPolicy | None = None,
    now: datetime | None = None,
) -> RetentionResult:
    """Prune expired records. Safe to run repeatedly."""

    active_policy = policy or RetentionPolicy()
    reference_time = now or datetime.utcnow()

    risk_event_result = await session.execute(
        delete(RiskEvent).where(
            RiskEvent.published_at < reference_time - timedelta(days=active_policy.risk_event_days)
        )
    )
    feed_result = await session.execute(
        delete(UserNewsFeed).where(
            UserNewsFeed.surfaced_at < reference_time - timedelta(days=active_policy.feed_days)
        )
    )
    processed_result = await session.execute(
        delete(NewsArticleProcessed).where(
            NewsArticleProcessed.processed_at
            < reference_time - timedelta(days=active_policy.processed_days)
        )
    )
    raw_result = await session.execute(
        delete(NewsArticleRaw).where(
            NewsArticleRaw.ingested_at < reference_time - timedelta(days=active_policy.raw_days)
        )
    )
    await session.commit()

    return RetentionResult(
        raw_deleted=raw_result.rowcount or 0,
        processed_deleted=processed_result.rowcount or 0,
        feed_deleted=feed_result.rowcount or 0,
        risk_events_deleted=risk_event_result.rowcount or 0,
    )
