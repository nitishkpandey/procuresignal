"""Tests for recording which suppliers an article names."""

import pytest
from procuresignal.models import ArticleSupplierMention
from procuresignal.suppliers.mentions import record_mentions
from procuresignal.suppliers.registry import add_alias, register_supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def registry(async_session: AsyncSession):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG")
    bosch = await register_supplier(async_session, canonical_name="Robert Bosch GmbH")
    await add_alias(async_session, supplier_id=bosch.id, alias="Bosch")
    await async_session.flush()
    return {"siemens": siemens, "bosch": bosch}


async def _mentions(session: AsyncSession) -> list[ArticleSupplierMention]:
    return list((await session.execute(select(ArticleSupplierMention))).scalars().all())


async def test_records_resolved_and_unresolved_alike(async_session: AsyncSession, registry) -> None:
    """An unresolved name is evidence of a missing alias, so it is kept."""
    resolutions = await record_mentions(
        async_session, processed_article_id=1, surface_forms=["Siemens AG", "Nobody Ltd"]
    )
    await async_session.flush()

    rows = await _mentions(async_session)
    assert len(rows) == 2
    assert {row.supplier_id is None for row in rows} == {False, True}
    assert [r.confidence for r in resolutions] == [1.0, 0.0]


async def test_resolved_mention_points_at_the_supplier(
    async_session: AsyncSession, registry
) -> None:
    await record_mentions(async_session, processed_article_id=1, surface_forms=["Bosch"])
    await async_session.flush()

    row = (await _mentions(async_session))[0]
    assert row.supplier_id == registry["bosch"].id
    assert row.surface_form == "Bosch"
    assert row.confidence == 1.0


async def test_re_running_enrichment_does_not_duplicate_mentions(
    async_session: AsyncSession, registry
) -> None:
    """Enrichment can run over an article more than once."""
    for _ in range(3):
        await record_mentions(async_session, processed_article_id=1, surface_forms=["Siemens AG"])
        await async_session.flush()

    assert len(await _mentions(async_session)) == 1


async def test_blank_and_repeated_surface_forms_are_ignored(
    async_session: AsyncSession, registry
) -> None:
    await record_mentions(
        async_session,
        processed_article_id=1,
        surface_forms=["Siemens AG", "  ", "Siemens AG", "", "siemens ag", None],
    )
    await async_session.flush()

    # Case and spacing variants of one name are one mention, not four.
    assert len(await _mentions(async_session)) == 1


async def test_an_empty_list_records_nothing(async_session: AsyncSession, registry) -> None:
    assert await record_mentions(async_session, processed_article_id=1, surface_forms=[]) == []
    await async_session.flush()

    assert await _mentions(async_session) == []


async def test_the_same_name_in_two_articles_is_two_mentions(
    async_session: AsyncSession, registry
) -> None:
    """Counting exposure across articles depends on this."""
    await record_mentions(async_session, processed_article_id=1, surface_forms=["Siemens AG"])
    await record_mentions(async_session, processed_article_id=2, surface_forms=["Siemens AG"])
    await async_session.flush()

    rows = await _mentions(async_session)
    assert len(rows) == 2
    assert {row.processed_article_id for row in rows} == {1, 2}


async def test_adding_a_new_name_to_an_article_keeps_the_old_ones(
    async_session: AsyncSession, registry
) -> None:
    await record_mentions(async_session, processed_article_id=1, surface_forms=["Siemens AG"])
    await async_session.flush()

    await record_mentions(
        async_session, processed_article_id=1, surface_forms=["Siemens AG", "Bosch"]
    )
    await async_session.flush()

    rows = await _mentions(async_session)
    assert {row.surface_form for row in rows} == {"Siemens AG", "Bosch"}


async def test_resolutions_are_returned_in_input_order(
    async_session: AsyncSession, registry
) -> None:
    resolutions = await record_mentions(
        async_session, processed_article_id=1, surface_forms=["Nobody Ltd", "Siemens AG"]
    )

    assert [r.surface_form for r in resolutions] == ["Nobody Ltd", "Siemens AG"]
    assert [r.resolved for r in resolutions] == [False, True]
