"""Attach supplier identity to data written before the registry existed.

Deliberately not a migration step. Resolving every historical article inside a schema
migration would hold one transaction open across the whole table, and this needs to be
run again each time the registry gains aliases — which migrations must never be.
"""

import logging
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import (
    ArticleSupplierMention,
    NewsArticleProcessed,
    RiskEvent,
    UserNewsPreference,
)

from .mentions import record_mentions
from .resolver import resolve_many

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class BackfillSummary:
    """What the run touched.

    The resolved and unresolved counts are the point: they say how much of the corpus
    the registry actually covers, which is otherwise a guess.
    """

    articles_scanned: int = 0
    mentions_created: int = 0
    mentions_resolved: int = 0
    mentions_unresolved: int = 0
    preferences_updated: int = 0
    risk_events_updated: int = 0

    @property
    def coverage(self) -> float:
        total = self.mentions_resolved + self.mentions_unresolved
        return self.mentions_resolved / total if total else 0.0


async def _resolved_public_ids(session: AsyncSession, names: list[str] | None) -> list[str]:
    resolutions = await resolve_many(session, names or [])
    return sorted({r.public_id for r in resolutions if r.public_id})


async def _backfill_mentions(
    session: AsyncSession, summary: BackfillSummary, batch_size: int
) -> BackfillSummary:
    offset = 0

    while True:
        articles = (
            (
                await session.execute(
                    select(NewsArticleProcessed)
                    .order_by(NewsArticleProcessed.id)
                    .offset(offset)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not articles:
            return summary

        article_ids = [article.id for article in articles]
        before = await _count_mentions(session, article_ids)

        for article in articles:
            await record_mentions(
                session,
                processed_article_id=article.id,
                surface_forms=article.detected_suppliers or [],
            )
        await session.flush()

        await _retry_unresolved(session, article_ids)
        await session.flush()

        # Counted from the rows themselves rather than from what each call returned.
        # record_mentions reports on names it was given whether or not they were new,
        # so summing its results counts the same mention more than once.
        resolved, unresolved = await _mention_coverage(session, article_ids)

        summary = replace(
            summary,
            articles_scanned=summary.articles_scanned + len(articles),
            mentions_created=summary.mentions_created
            + (await _count_mentions(session, article_ids) - before),
            mentions_resolved=summary.mentions_resolved + resolved,
            mentions_unresolved=summary.mentions_unresolved + unresolved,
        )
        await session.commit()
        offset += batch_size


async def _count_mentions(session: AsyncSession, article_ids: list[int]) -> int:
    rows = (
        await session.execute(
            select(ArticleSupplierMention.id).where(
                ArticleSupplierMention.processed_article_id.in_(article_ids)
            )
        )
    ).all()
    return len(rows)


async def _mention_coverage(session: AsyncSession, article_ids: list[int]) -> tuple[int, int]:
    """How many mentions for these articles carry a supplier, and how many do not."""

    rows = (
        (
            await session.execute(
                select(ArticleSupplierMention.supplier_id).where(
                    ArticleSupplierMention.processed_article_id.in_(article_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    resolved = sum(1 for supplier_id in rows if supplier_id is not None)
    return resolved, len(rows) - resolved


async def _retry_unresolved(session: AsyncSession, article_ids: list[int]) -> None:
    """Re-resolve mentions an earlier run could not place.

    This is why the backfill is re-runnable: an alias added since then rescues them.
    """

    stale = (
        (
            await session.execute(
                select(ArticleSupplierMention)
                .where(ArticleSupplierMention.supplier_id.is_(None))
                .where(ArticleSupplierMention.processed_article_id.in_(article_ids))
            )
        )
        .scalars()
        .all()
    )
    if not stale:
        return

    retries = await resolve_many(session, [row.surface_form for row in stale])
    for row, resolution in zip(stale, retries):
        if resolution.resolved:
            row.supplier_id = resolution.supplier_id
            row.confidence = resolution.confidence


async def _backfill_preferences(session: AsyncSession, summary: BackfillSummary) -> BackfillSummary:
    preferences = (await session.execute(select(UserNewsPreference))).scalars().all()

    updated = 0
    for preference in preferences:
        preferred = await _resolved_public_ids(session, preference.preferred_suppliers)
        excluded = await _resolved_public_ids(session, preference.excluded_suppliers)

        if preferred == (preference.preferred_supplier_ids or []) and excluded == (
            preference.excluded_supplier_ids or []
        ):
            continue

        preference.preferred_supplier_ids = preferred
        preference.excluded_supplier_ids = excluded
        updated += 1

    await session.commit()
    return replace(summary, preferences_updated=summary.preferences_updated + updated)


async def _backfill_risk_events(session: AsyncSession, summary: BackfillSummary) -> BackfillSummary:
    events = (await session.execute(select(RiskEvent))).scalars().all()

    updated = 0
    for event in events:
        resolved = await _resolved_public_ids(session, event.affected_suppliers)
        if resolved == (event.affected_supplier_ids or []):
            continue
        event.affected_supplier_ids = resolved
        updated += 1

    await session.commit()
    return replace(summary, risk_events_updated=summary.risk_events_updated + updated)


async def backfill_supplier_identity(
    session: AsyncSession, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> BackfillSummary:
    """Resolve supplier identity across articles, preferences, and risk events.

    Idempotent and batched, committing per batch so a long run does not lose its
    progress or hold one transaction open across the whole table.
    """

    summary = BackfillSummary()
    summary = await _backfill_mentions(session, summary, batch_size)
    summary = await _backfill_preferences(session, summary)
    summary = await _backfill_risk_events(session, summary)

    logger.info(
        "supplier backfill complete: %s articles, %s mentions created, "
        "%.0f%% resolved, %s preferences, %s risk events",
        summary.articles_scanned,
        summary.mentions_created,
        summary.coverage * 100,
        summary.preferences_updated,
        summary.risk_events_updated,
    )
    return summary
