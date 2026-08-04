"""Sanctions screening as it runs in production, not as a function in isolation.

Task 6 delivered the screening function and the structured names, but nothing called
it. These tests exist so "designations are screened" is a statement about the running
system rather than about a unit test.
"""

from datetime import datetime

import pytest
from procuresignal.models import ArticleSupplierMention, NewsArticleProcessed, NewsArticleRaw
from procuresignal.suppliers.registry import add_alias, register_supplier
from procuresignal.suppliers.screening import screen_processed_articles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def registry(async_session: AsyncSession):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG")
    await add_alias(async_session, supplier_id=siemens.id, alias="Siemens Aktiengesellschaft")
    await async_session.commit()
    return {"siemens": siemens}


async def _designation(session: AsyncSession, marker: str, names: list[str]) -> int:
    """A sanctions designation as the structured adapter ingests one."""
    raw = NewsArticleRaw(
        provider="eu_sanctions",
        provider_article_id=f"eu-sanctions:{marker}",
        query_group="sanctions",
        ingest_hash=marker,
        title=f"EU sanctions designation: {names[0]}",
        description="Entity; EU reference EU.1",
        content_snippet="Entity; EU reference EU.1",
        article_url="https://webgate.ec.europa.eu/fsd",
        source_name="DG FISMA",
        published_at=datetime(2026, 8, 1),
        ingested_at=datetime(2026, 8, 1),
        language="en",
        raw_payload_json={"designation_id": marker, "designation_names": names},
    )
    session.add(raw)
    await session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=raw.title,
        summary=raw.description,
        top_level_category="regulatory",
        signal_tags=["sanctions"],
        priority_signal="sanctions",
        detected_suppliers=[],
        detected_regions=[],
        detected_categories=["regulatory"],
        processed_at=datetime(2026, 8, 1),
    )
    session.add(processed)
    await session.flush()
    await session.commit()
    return processed.id


async def test_a_designation_alias_flags_a_registered_supplier(
    async_session: AsyncSession, registry
) -> None:
    """The compliance case: the designation spells the name differently to the registry."""
    article_id = await _designation(async_session, "d1", ["Siemens Aktiengesellschaft", "SIEMENS"])

    summary = await screen_processed_articles(async_session)

    assert summary.designations_screened == 1
    assert summary.suppliers_flagged == 1

    mentions = (
        (
            await async_session.execute(
                select(ArticleSupplierMention).where(
                    ArticleSupplierMention.processed_article_id == article_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert registry["siemens"].id in {m.supplier_id for m in mentions}


async def test_an_unplaceable_designation_is_recorded_not_dropped(
    async_session: AsyncSession, registry
) -> None:
    """Coverage has to be visible, or screening that finds nothing looks like success."""
    article_id = await _designation(async_session, "d2", ["Entirely Unknown Entity"])

    summary = await screen_processed_articles(async_session)

    assert summary.unmatched_names == 1
    mention = (
        (
            await async_session.execute(
                select(ArticleSupplierMention).where(
                    ArticleSupplierMention.processed_article_id == article_id
                )
            )
        )
        .scalars()
        .one()
    )
    assert mention.supplier_id is None
    assert mention.surface_form == "Entirely Unknown Entity"


async def test_screening_does_not_flag_a_different_legal_entity(
    async_session: AsyncSession, registry
) -> None:
    await register_supplier(async_session, canonical_name="Siemens Energy AG")
    await async_session.commit()
    await _designation(async_session, "d3", ["Siemens Energy AG"])

    await screen_processed_articles(async_session)

    mentions = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert registry["siemens"].id not in {m.supplier_id for m in mentions}


async def test_ordinary_articles_are_not_treated_as_designations(
    async_session: AsyncSession, registry
) -> None:
    raw = NewsArticleRaw(
        provider="rss",
        provider_article_id="n1",
        query_group="q",
        ingest_hash="n1",
        title="Siemens AG opens a plant",
        description="A new plant.",
        content_snippet="A new plant.",
        article_url="https://example.test/n1",
        source_name="Wire",
        published_at=datetime(2026, 8, 1),
        ingested_at=datetime(2026, 8, 1),
        language="en",
    )
    async_session.add(raw)
    await async_session.flush()
    async_session.add(
        NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=raw.title,
            summary=raw.description,
            top_level_category="logistics",
            signal_tags=[],
            priority_signal=None,
            detected_suppliers=["Siemens AG"],
            detected_regions=[],
            detected_categories=["logistics"],
            processed_at=datetime(2026, 8, 1),
        )
    )
    await async_session.commit()

    summary = await screen_processed_articles(async_session)

    assert summary.designations_screened == 0


async def test_screening_is_idempotent(async_session: AsyncSession, registry) -> None:
    await _designation(async_session, "d4", ["Siemens Aktiengesellschaft"])

    first = await screen_processed_articles(async_session)
    second = await screen_processed_articles(async_session)

    assert first.designations_screened == 1
    assert second.designations_screened == 1

    mentions = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(mentions) == 1
