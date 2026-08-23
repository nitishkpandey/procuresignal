"""Retention, driven by the personal-data registry.

Every window lives in `procuresignal.privacy.inventory`, and this job prunes whatever the
registry says has one. A hand-written list here would be a second source of truth, and the
failure mode is specific: a table documented with a 400-day window that nothing actually
prunes is a false statement in a compliance document, and it stays false until somebody
audits the code rather than the paperwork.

A test asserts the two agree, so the drift cannot start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Base
from procuresignal.privacy.inventory import INVENTORY


def _registry_days(table: str) -> int:
    """The window the registry records for a table.

    Read rather than repeated, so `RetentionPolicy` and the inventory cannot disagree
    about how long an article is kept.
    """

    for entry in INVENTORY:
        if entry.table == table and entry.retention_days is not None:
            return entry.retention_days
    raise KeyError(f"{table} has no retention window in the registry")


@dataclass(slots=True)
class RetentionPolicy:
    """Windows for the four tables other modules ask about by name.

    Kept as named fields because search, scoring and the agent tools all read them to
    decide how far back to look. The values come from the registry rather than being
    written twice.
    """

    raw_days: int = field(default_factory=lambda: _registry_days("news_articles_raw"))
    processed_days: int = field(default_factory=lambda: _registry_days("news_articles_processed"))
    feed_days: int = field(default_factory=lambda: _registry_days("user_news_feed"))
    risk_event_days: int = field(default_factory=lambda: _registry_days("risk_events"))


@dataclass(slots=True)
class RetentionResult:
    raw_deleted: int
    processed_deleted: int
    feed_deleted: int
    risk_events_deleted: int
    # Every table the registry gave a window, including the ones with no named field
    # above. What was actually pruned, which is the number a privacy review asks for.
    by_table: dict[str, int] = field(default_factory=dict)


async def prune_expired_records(
    session: AsyncSession,
    *,
    policy: RetentionPolicy | None = None,
    now: datetime | None = None,
) -> RetentionResult:
    """Delete rows past their retention window. Safe to run repeatedly.

    Ordering is immaterial: the foreign keys that exist cascade, and the older tables
    reference each other by bare integer rather than by constraint.
    """

    active_policy = policy or RetentionPolicy()
    reference_time = now or datetime.utcnow()

    # The four tables callers can override by name. Everything else takes the registry's
    # window as written.
    overrides = {
        "news_articles_raw": active_policy.raw_days,
        "news_articles_processed": active_policy.processed_days,
        "user_news_feed": active_policy.feed_days,
        "risk_events": active_policy.risk_event_days,
    }

    by_table: dict[str, int] = {}
    for entry in INVENTORY:
        if entry.retention_days is None:
            continue

        days = overrides.get(entry.table, entry.retention_days)
        table = Base.metadata.tables[entry.table]
        result = await session.execute(
            delete(table).where(
                table.c[entry.retention_column] < reference_time - timedelta(days=days)
            )
        )
        by_table[entry.table] = getattr(result, "rowcount", 0) or 0

    await session.commit()

    return RetentionResult(
        raw_deleted=by_table.get("news_articles_raw", 0),
        processed_deleted=by_table.get("news_articles_processed", 0),
        feed_deleted=by_table.get("user_news_feed", 0),
        risk_events_deleted=by_table.get("risk_events", 0),
        by_table=by_table,
    )
