"""Screening sanctions designations against the supplier registry.

A miss here is a compliance failure rather than a poor feed, which is why screening
resolves every name a designation carries instead of comparing the primary one.
"""

import pytest
from procuresignal.suppliers.registry import add_alias, register_supplier
from procuresignal.suppliers.screening import screen_designation
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def registry(async_session: AsyncSession):
    siemens = await register_supplier(async_session, canonical_name="Siemens AG", country="DE")
    energy = await register_supplier(
        async_session, canonical_name="Siemens Energy AG", country="DE"
    )
    await add_alias(async_session, supplier_id=siemens.id, alias="Siemens Aktiengesellschaft")
    await async_session.flush()
    return {"siemens": siemens, "energy": energy}


async def test_the_primary_name_matches(async_session: AsyncSession, registry) -> None:
    result = await screen_designation(async_session, primary_name="Siemens AG", aliases=[])

    assert [hit.supplier_id for hit in result.hits] == [registry["siemens"].id]


async def test_an_alias_matches_when_the_primary_name_does_not(
    async_session: AsyncSession, registry
) -> None:
    """The designation may use a legal spelling nobody else writes."""
    result = await screen_designation(
        async_session,
        primary_name="Some Registry Spelling Nobody Uses",
        aliases=["Siemens Aktiengesellschaft"],
    )

    assert [hit.supplier_id for hit in result.hits] == [registry["siemens"].id]
    assert result.hits[0].matched_name == "Siemens Aktiengesellschaft"


async def test_a_designation_hitting_several_suppliers_reports_all(
    async_session: AsyncSession, registry
) -> None:
    result = await screen_designation(
        async_session, primary_name="Siemens AG", aliases=["Siemens Energy AG"]
    )

    assert {hit.supplier_id for hit in result.hits} == {
        registry["siemens"].id,
        registry["energy"].id,
    }


async def test_one_supplier_is_reported_once_however_many_names_hit(
    async_session: AsyncSession, registry
) -> None:
    result = await screen_designation(
        async_session,
        primary_name="Siemens AG",
        aliases=["Siemens", "Siemens Aktiengesellschaft", "siemens ag"],
    )

    assert len(result.hits) == 1


async def test_an_unknown_designation_produces_no_hits(
    async_session: AsyncSession, registry
) -> None:
    result = await screen_designation(
        async_session, primary_name="Entirely Unknown Entity", aliases=["Also Unknown"]
    )

    assert result.hits == []


async def test_screening_does_not_match_a_different_legal_entity(
    async_session: AsyncSession, registry
) -> None:
    """Sanctioning the spinoff must not flag the parent."""
    result = await screen_designation(async_session, primary_name="Siemens Energy AG", aliases=[])

    assert [hit.supplier_id for hit in result.hits] == [registry["energy"].id]
    assert registry["siemens"].id not in {hit.supplier_id for hit in result.hits}


async def test_blank_names_are_ignored(async_session: AsyncSession, registry) -> None:
    result = await screen_designation(
        async_session, primary_name="  ", aliases=["", "   ", "Siemens AG"]
    )

    assert [hit.supplier_id for hit in result.hits] == [registry["siemens"].id]


async def test_a_merged_away_supplier_is_not_reported(
    async_session: AsyncSession, registry
) -> None:
    registry["energy"].is_active = False
    await async_session.flush()

    result = await screen_designation(async_session, primary_name="Siemens Energy AG", aliases=[])

    assert result.hits == []


async def test_unmatched_names_are_reported_so_coverage_is_visible(
    async_session: AsyncSession, registry
) -> None:
    """Screening that silently finds nothing is indistinguishable from screening that works."""
    result = await screen_designation(
        async_session, primary_name="Unknown Entity", aliases=["Siemens AG"]
    )

    assert result.unmatched_names == ["Unknown Entity"]
    assert [hit.supplier_id for hit in result.hits] == [registry["siemens"].id]


# --- risk events carry canonical identity ----------------------------------------


async def test_risk_events_record_the_suppliers_they_resolved_to(
    async_session: AsyncSession, registry
) -> None:
    """Phase 4 watchlists and Phase 5 exposure scoring both key off this."""
    from datetime import datetime

    from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, RiskEvent
    from procuresignal.risk_events.persistence import generate_risk_events
    from sqlalchemy import select

    raw = NewsArticleRaw(
        provider="rss",
        provider_article_id="r1",
        query_group="q",
        ingest_hash="r1",
        title="Attack disrupts exports from Qatar hitting Siemens AG",
        description="An attack threatens shipments from Qatar to Siemens AG in Germany.",
        content_snippet="Buyers are reviewing the conflict impact on supply.",
        article_url="https://example.test/r1",
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
            top_level_category="energy",
            signal_tags=["conflict"],
            priority_signal="geopolitical",
            detected_suppliers=["Siemens AG"],
            detected_regions=["Qatar", "Germany"],
            detected_categories=["logistics"],
            processed_at=datetime(2026, 8, 1),
        )
    )
    await async_session.commit()

    await generate_risk_events(async_session, days_back=3650)

    events = (await async_session.execute(select(RiskEvent))).scalars().all()
    assert events, "expected the attack to produce a risk event"
    assert registry["siemens"].public_id in events[0].affected_supplier_ids
    # The free text is kept beside it, not replaced.
    assert events[0].affected_suppliers == ["Siemens AG"]
