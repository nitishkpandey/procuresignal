"""Backfilling supplier identity onto data written before the registry existed."""

from datetime import datetime

import pytest
from procuresignal.models import (
    ArticleSupplierMention,
    NewsArticleProcessed,
    NewsArticleRaw,
    RiskEvent,
    UserNewsPreference,
)
from procuresignal.suppliers.backfill import backfill_supplier_identity
from procuresignal.suppliers.registry import register_supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def registry(async_session: AsyncSession):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.commit()
    return {"siemens": siemens}


async def _article(session: AsyncSession, marker: str, suppliers: list[str]) -> int:
    raw = NewsArticleRaw(
        provider="rss",
        provider_article_id=marker,
        query_group="q",
        ingest_hash=marker,
        title=f"{marker} headline",
        description=f"{marker} description",
        content_snippet=f"{marker} snippet",
        article_url=f"https://example.test/{marker}",
        source_name="Wire",
        published_at=datetime(2026, 8, 1),
        ingested_at=datetime(2026, 8, 1),
        language="en",
    )
    session.add(raw)
    await session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=raw.title,
        summary=raw.description,
        top_level_category="logistics",
        signal_tags=[],
        priority_signal=None,
        detected_suppliers=suppliers,
        detected_regions=[],
        detected_categories=["logistics"],
        processed_at=datetime(2026, 8, 1),
    )
    session.add(processed)
    await session.flush()
    return processed.id


async def test_existing_articles_gain_mentions(async_session: AsyncSession, registry) -> None:
    await _article(async_session, "a1", ["Siemens AG", "Nobody Ltd"])
    await async_session.commit()

    summary = await backfill_supplier_identity(async_session)

    assert summary.mentions_created == 2
    assert summary.mentions_resolved == 1
    assert summary.mentions_unresolved == 1


async def test_backfill_is_safe_to_re_run(async_session: AsyncSession, registry) -> None:
    """It will be run again after the registry gains aliases."""
    await _article(async_session, "a1", ["Siemens AG"])
    await async_session.commit()

    first = await backfill_supplier_identity(async_session)
    second = await backfill_supplier_identity(async_session)

    assert first.mentions_created == 1
    assert second.mentions_created == 0

    rows = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 1


async def test_re_running_picks_up_newly_added_aliases(
    async_session: AsyncSession, registry
) -> None:
    """The reason this is a script and not a one-shot migration step."""
    from procuresignal.suppliers.registry import add_alias

    await _article(async_session, "a1", ["Siemens Aktiengesellschaft"])
    await async_session.commit()

    first = await backfill_supplier_identity(async_session)
    assert first.mentions_unresolved == 1

    await add_alias(
        async_session, supplier_id=registry["siemens"].id, alias="Siemens Aktiengesellschaft"
    )
    await async_session.commit()

    second = await backfill_supplier_identity(async_session)

    assert second.mentions_resolved == 1
    mention = (await async_session.execute(select(ArticleSupplierMention))).scalars().one()
    assert mention.supplier_id == registry["siemens"].id


async def test_existing_preferences_gain_resolved_ids(
    async_session: AsyncSession, registry
) -> None:
    """Without this, users who set preferences before the registry get no benefit."""
    async_session.add(
        UserNewsPreference(
            user_id="buyer",
            preferred_categories=[],
            preferred_suppliers=["Siemens"],
            preferred_regions=[],
            preferred_signals=[],
            excluded_categories=[],
            excluded_suppliers=["Nobody Ltd"],
            excluded_regions=[],
            excluded_signals=[],
            excluded_topics=[],
        )
    )
    await async_session.commit()

    summary = await backfill_supplier_identity(async_session)

    preference = (await async_session.execute(select(UserNewsPreference))).scalars().one()
    assert summary.preferences_updated == 1
    assert preference.preferred_supplier_ids == [registry["siemens"].public_id]
    assert preference.excluded_supplier_ids == []
    # The text the user typed is untouched.
    assert preference.preferred_suppliers == ["Siemens"]


async def test_preferences_already_resolved_are_not_counted_again(
    async_session: AsyncSession, registry
) -> None:
    async_session.add(
        UserNewsPreference(
            user_id="buyer",
            preferred_categories=[],
            preferred_suppliers=["Siemens"],
            preferred_regions=[],
            preferred_signals=[],
            excluded_categories=[],
            excluded_suppliers=[],
            excluded_regions=[],
            excluded_signals=[],
            excluded_topics=[],
        )
    )
    await async_session.commit()

    await backfill_supplier_identity(async_session)
    second = await backfill_supplier_identity(async_session)

    assert second.preferences_updated == 0


async def test_existing_risk_events_gain_resolved_ids(
    async_session: AsyncSession, registry
) -> None:
    article_id = await _article(async_session, "a1", ["Siemens AG"])
    async_session.add(
        RiskEvent(
            event_key="k1",
            processed_article_id=article_id,
            risk_type="supply_disruption",
            severity="high",
            confidence=0.9,
            affected_suppliers=["Siemens AG"],
            affected_locations=[],
            affected_categories=["logistics"],
            evidence_snippet="evidence",
            recommendation="review",
            source_name="Wire",
            source_url="https://example.test/a1",
            published_at=datetime(2026, 8, 1),
            status="new",
        )
    )
    await async_session.commit()

    summary = await backfill_supplier_identity(async_session)

    event = (await async_session.execute(select(RiskEvent))).scalars().one()
    assert summary.risk_events_updated == 1
    assert event.affected_supplier_ids == [registry["siemens"].public_id]
    assert event.affected_suppliers == ["Siemens AG"]


async def test_batching_covers_every_row(async_session: AsyncSession, registry) -> None:
    """A small batch size must not silently stop after the first page."""
    for index in range(7):
        await _article(async_session, f"a{index}", ["Siemens AG"])
    await async_session.commit()

    summary = await backfill_supplier_identity(async_session, batch_size=2)

    assert summary.articles_scanned == 7
    assert summary.mentions_created == 7


async def test_an_empty_database_is_not_an_error(async_session: AsyncSession) -> None:
    summary = await backfill_supplier_identity(async_session)

    assert summary.articles_scanned == 0
    assert summary.mentions_created == 0
