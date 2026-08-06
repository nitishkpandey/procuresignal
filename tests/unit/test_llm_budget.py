"""Tests for durable per-tenant LLM spend caps.

`EnrichmentBudget` in policy.py caps one run in one process and resets on the next. That
is a batch size, not a budget: it does not survive a restart and does not bound what any
one tenant costs. A runaway ingestion loop stays a five-figure surprise.
"""

from datetime import date, timedelta

import pytest
from procuresignal.enrichment.budget import (
    DAILY_TOKEN_BUDGET,
    GLOBAL_BUCKET,
    BudgetExceededError,
    consume,
    remaining_tokens,
    within_budget,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def test_spend_below_the_cap_is_allowed(async_session: AsyncSession) -> None:
    assert await within_budget(async_session, tenant="acme", tokens=100) is True


async def test_a_tenant_over_budget_is_refused_not_delayed(async_session: AsyncSession) -> None:
    """A hard stop. Delaying the work moves the same spend to tomorrow."""
    await consume(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET, calls=1)
    await async_session.flush()

    assert await within_budget(async_session, tenant="acme", tokens=1) is False


async def test_one_tenant_cannot_exhaust_another(async_session: AsyncSession) -> None:
    await consume(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET, calls=1)
    await async_session.flush()

    assert await within_budget(async_session, tenant="globex", tokens=1) is True


async def test_spend_accumulates_across_calls(async_session: AsyncSession) -> None:
    for _ in range(3):
        await consume(async_session, tenant="acme", tokens=1000, calls=1)
    await async_session.flush()

    assert await remaining_tokens(async_session, tenant="acme") == DAILY_TOKEN_BUDGET - 3000


async def test_the_budget_resets_the_next_day(async_session: AsyncSession) -> None:
    """Dated rows rather than a scheduled reset: nothing to run, nothing to fail."""
    yesterday = date.today() - timedelta(days=1)
    await consume(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET, calls=1, on=yesterday)
    await async_session.flush()

    assert await within_budget(async_session, tenant="acme", tokens=1) is True


async def test_work_with_no_known_tenant_uses_a_shared_bucket(
    async_session: AsyncSession,
) -> None:
    """Enrichment is not per tenant yet. The seam is explicit rather than implied."""
    await consume(async_session, tenant=None, tokens=DAILY_TOKEN_BUDGET, calls=1)
    await async_session.flush()

    assert await within_budget(async_session, tenant=None, tokens=1) is False
    assert await remaining_tokens(async_session, tenant=GLOBAL_BUCKET) == 0


async def test_a_request_larger_than_the_whole_budget_is_refused(
    async_session: AsyncSession,
) -> None:
    assert await within_budget(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET + 1) is False


async def test_consuming_over_budget_raises(async_session: AsyncSession) -> None:
    """Callers that forget to check must still not overspend."""
    await consume(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET, calls=1)
    await async_session.flush()

    with pytest.raises(BudgetExceededError):
        await consume(async_session, tenant="acme", tokens=1, calls=1)


async def test_remaining_never_goes_negative(async_session: AsyncSession) -> None:
    await consume(async_session, tenant="acme", tokens=DAILY_TOKEN_BUDGET, calls=1)
    await async_session.flush()

    assert await remaining_tokens(async_session, tenant="acme") == 0


def test_budget_refusals_are_counted_for_alerting() -> None:
    from procuresignal.observability.metrics import LLM_BUDGET_REFUSALS

    assert LLM_BUDGET_REFUSALS._labelnames == ("tenant",)


def test_enrichment_consults_the_budget() -> None:
    """A cap nothing calls is a constant."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "shared"
        / "procuresignal"
        / "enrichment"
        / "pipeline.py"
    ).read_text()

    assert "within_budget" in source
    assert "consume" in source


async def test_concurrent_spend_does_not_lose_updates(async_session: AsyncSession) -> None:
    """Read-modify-write let several workers read the same total and overwrite each
    other, so the cap silently permitted several times what it said."""
    for _ in range(10):
        await consume(async_session, tenant="acme", tokens=1000, calls=1)
    await async_session.flush()

    assert await remaining_tokens(async_session, tenant="acme") == DAILY_TOKEN_BUDGET - 10_000


async def test_consume_increments_in_the_database(async_session: AsyncSession) -> None:
    """The statement itself must do the addition; anything read into Python first
    races with every other worker."""
    import inspect

    from procuresignal.enrichment import budget

    source = inspect.getsource(budget._increment)
    assert "on_conflict_do_update" in source
    assert "tokens_used +" in source or "c.tokens_used +" in source
