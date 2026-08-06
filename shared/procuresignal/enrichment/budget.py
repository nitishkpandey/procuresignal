"""Durable per-tenant caps on LLM spend.

`EnrichmentBudget` in policy.py bounds one run in one process and resets on the next,
so it is a batch size rather than a budget: it does not survive a restart and does not
bound what any single tenant costs. Enrichment cost scales with articles times tenants,
and one runaway ingestion loop is a five-figure surprise.

A hard stop, not a throttle. Refusing the call is the point; delaying it moves the same
spend to tomorrow.
"""

import os
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import LlmSpend

# Work that has no organization attached. Enrichment is currently global rather than
# per tenant, so this is where most spend lands today; the seam is named explicitly
# rather than left implied, so per-tenant enrichment can adopt it without redesign.
GLOBAL_BUCKET = "__global__"


def _daily_token_budget() -> int:
    return max(1, int(os.getenv("LLM_DAILY_TOKEN_BUDGET", "500000")))


DAILY_TOKEN_BUDGET = _daily_token_budget()


class BudgetExceededError(Exception):
    """Raised when consuming would take a tenant past its daily cap."""


def _bucket(tenant: str | None) -> str:
    return tenant or GLOBAL_BUCKET


async def _row(session: AsyncSession, tenant: str | None, on: date | None) -> LlmSpend | None:
    return (
        await session.execute(
            select(LlmSpend)
            .where(LlmSpend.tenant == _bucket(tenant))
            .where(LlmSpend.spend_date == (on or date.today()))
        )
    ).scalar_one_or_none()


async def remaining_tokens(
    session: AsyncSession, *, tenant: str | None, on: date | None = None
) -> int:
    """Tokens left for this tenant today. Never negative."""

    row = await _row(session, tenant, on)
    used = row.tokens_used if row else 0
    return max(0, DAILY_TOKEN_BUDGET - used)


async def within_budget(
    session: AsyncSession, *, tenant: str | None, tokens: int, on: date | None = None
) -> bool:
    """Whether this many tokens can still be spent today."""

    return tokens <= await remaining_tokens(session, tenant=tenant, on=on)


async def consume(
    session: AsyncSession,
    *,
    tenant: str | None,
    tokens: int,
    calls: int = 1,
    on: date | None = None,
) -> None:
    """Record spend, refusing to exceed the cap.

    Checked here as well as by callers, so forgetting to ask still cannot overspend.
    """

    if not await within_budget(session, tenant=tenant, tokens=tokens, on=on):
        raise BudgetExceededError(
            f"{_bucket(tenant)} has no daily LLM budget left for {tokens} tokens"
        )

    row = await _row(session, tenant, on)
    if row is None:
        row = LlmSpend(
            tenant=_bucket(tenant),
            spend_date=on or date.today(),
            tokens_used=0,
            calls_made=0,
        )
        session.add(row)

    row.tokens_used += tokens
    row.calls_made += calls
    await session.flush()


async def consume_overage(
    session: AsyncSession, *, tenant: str | None, tokens: int, on: date | None = None
) -> None:
    """Record spend that already happened, even though it exceeds the cap.

    A call can finish just as the budget runs out. Dropping the accounting would
    understate what the tenant actually cost and let the next run overspend again.
    """

    row = await _row(session, tenant, on)
    if row is None:
        row = LlmSpend(
            tenant=_bucket(tenant), spend_date=on or date.today(), tokens_used=0, calls_made=0
        )
        session.add(row)

    row.tokens_used += tokens
    row.calls_made += 1
    await session.flush()
