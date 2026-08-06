"""Screen sanctions designations against the supplier registry.

A designation names one entity in several ways: a primary registry spelling plus the
aliases the issuing authority recorded. Comparing only the primary name is how a
screening control reports a false negative, which in the EU is a compliance failure
rather than a poor feed. Every name is resolved.
"""

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import record_screening
from procuresignal.auth.audit import record_audit
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw

from .mentions import record_mentions
from .resolver import resolve_many

logger = logging.getLogger(__name__)

# Written by the structured sanctions adapter into the raw payload it carries
# through enrichment. Its presence is what marks an article as a designation.
DESIGNATION_NAMES_KEY = "designation_names"


@dataclass(frozen=True)
class ScreeningHit:
    """A registered supplier named by a designation."""

    supplier_id: int
    public_id: str
    matched_name: str


@dataclass(frozen=True)
class ScreeningResult:
    """What screening one designation found, and what it could not place."""

    hits: list[ScreeningHit] = field(default_factory=list)
    # Names that resolved to nothing. Reported rather than discarded: screening that
    # silently finds nothing looks exactly like screening that works.
    unmatched_names: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.hits)


async def screen_designation(
    session: AsyncSession,
    *,
    primary_name: str,
    aliases: Optional[Iterable[str]] = None,
) -> ScreeningResult:
    """Resolve every name a designation carries against the registry."""

    names = [name for name in [primary_name, *(aliases or [])] if (name or "").strip()]
    if not names:
        return ScreeningResult()

    resolutions = await resolve_many(session, names)

    hits: list[ScreeningHit] = []
    unmatched: list[str] = []
    seen_suppliers: set[int] = set()

    for resolution in resolutions:
        if resolution.supplier_id is None or resolution.public_id is None:
            unmatched.append(resolution.surface_form)
            continue
        # One supplier is reported once however many of its spellings the designation
        # happens to list.
        if resolution.supplier_id in seen_suppliers:
            continue
        seen_suppliers.add(resolution.supplier_id)
        hits.append(
            ScreeningHit(
                supplier_id=resolution.supplier_id,
                public_id=resolution.public_id,
                matched_name=resolution.surface_form,
            )
        )

    return ScreeningResult(hits=hits, unmatched_names=unmatched)


@dataclass(frozen=True)
class ScreeningRunSummary:
    """What one screening pass covered.

    The unmatched count is the compliance-relevant number. Screening that quietly
    matches nothing is indistinguishable from screening that works, so coverage has to
    be reported rather than inferred.
    """

    designations_screened: int = 0
    suppliers_flagged: int = 0
    unmatched_names: int = 0


async def screen_processed_articles(
    session: AsyncSession, *, limit: int = 1000
) -> ScreeningRunSummary:
    """Screen every ingested sanctions designation against the registry.

    This is the production entry point. `screen_designation` on its own resolves names;
    without this, nothing called it and no designation was ever actually screened.

    Matches and misses are both written as article supplier mentions, which puts them
    on the same footing as any other supplier reference: the misses surface in the
    unresolved queue, and the matches carry into risk events and exposure scoring.
    Idempotent, because the mention writer will not duplicate a name already recorded.
    """

    # The payload lives on the raw article, so screening joins rather than relying on
    # a denormalized copy that could fall out of step with what was ingested.
    rows = (
        await session.execute(
            select(NewsArticleProcessed.id, NewsArticleRaw.raw_payload_json)
            .join(NewsArticleRaw, NewsArticleRaw.id == NewsArticleProcessed.raw_article_id)
            .where(NewsArticleRaw.raw_payload_json.is_not(None))
            .order_by(NewsArticleProcessed.id)
            .limit(limit)
        )
    ).all()

    screened = 0
    flagged = 0
    unmatched = 0

    for article_id, payload in rows:
        names = (payload or {}).get(DESIGNATION_NAMES_KEY) or []
        if not names:
            continue

        screened += 1
        result = await screen_designation(session, primary_name=names[0], aliases=names[1:])
        flagged += len(result.hits)
        unmatched += len(result.unmatched_names)

        await record_mentions(session, processed_article_id=article_id, surface_forms=names)

        # Audited per match, not only per run. A summary says how many were flagged;
        # a compliance control has to be able to say which, and when.
        for hit in result.hits:
            await record_audit(
                session,
                action="sanctions.supplier_flagged",
                outcome="success",
                resource_type="supplier",
                resource_id=hit.public_id,
                detail={
                    "matched_name": hit.matched_name,
                    "designation_article_id": article_id,
                },
            )

    record_screening("matched", flagged)
    record_screening("unmatched", unmatched)

    await record_audit(
        session,
        action="sanctions.screening_run",
        outcome="success",
        detail={
            "designations_screened": screened,
            "suppliers_flagged": flagged,
            # The number that matters: names the registry could not place are the
            # gap between screening running and screening working.
            "unmatched_names": unmatched,
        },
    )
    await session.commit()

    summary = ScreeningRunSummary(
        designations_screened=screened,
        suppliers_flagged=flagged,
        unmatched_names=unmatched,
    )
    logger.info(
        "sanctions screening: %s designations, %s suppliers flagged, %s names unplaced",
        summary.designations_screened,
        summary.suppliers_flagged,
        summary.unmatched_names,
    )
    return summary
