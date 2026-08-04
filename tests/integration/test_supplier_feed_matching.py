"""End-to-end: a watched supplier reaches the feed regardless of spelling.

Unit tests cover each layer, but only the whole path shows whether a user watching
"Siemens" actually receives an article that wrote "Siemens AG" — and, just as
importantly, does not receive one about Siemens Energy.
"""

from datetime import datetime

import pytest
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.personalization.pipeline import PersonalizationPipeline
from procuresignal.personalization.preference_manager import PreferenceManager
from procuresignal.suppliers.mentions import record_mentions
from procuresignal.suppliers.registry import register_supplier
from sqlalchemy.ext.asyncio import AsyncSession

ARTICLES = [
    ("Siemens AG", "Siemens AG halts a plant"),
    ("Siemens Energy AG", "Siemens Energy wins turbine deal"),
    ("Obscure Parts Ltd", "Obscure Parts Ltd reports a fire"),
]


@pytest.fixture
async def corpus(async_session: AsyncSession):
    # Siemens and its spinoff are registered; Obscure Parts deliberately is not.
    await register_supplier(async_session, canonical_name="Siemens AG")
    await register_supplier(async_session, canonical_name="Siemens Energy AG")

    for index, (supplier, title) in enumerate(ARTICLES, start=1):
        raw = NewsArticleRaw(
            provider="rss",
            provider_article_id=f"a{index}",
            query_group="q",
            ingest_hash=f"h{index}",
            title=title,
            description=title,
            content_snippet=title,
            article_url=f"https://example.test/{index}",
            source_name="Wire",
            published_at=datetime(2026, 8, 1),
            ingested_at=datetime(2026, 8, 1),
            language="en",
        )
        async_session.add(raw)
        await async_session.flush()

        processed = NewsArticleProcessed(
            raw_article_id=raw.id,
            normalized_title=title,
            summary=title,
            top_level_category="logistics",
            signal_tags=["disruption"],
            priority_signal=None,
            detected_suppliers=[supplier],
            detected_regions=[],
            detected_categories=["logistics"],
            processed_at=datetime(2026, 8, 1),
        )
        async_session.add(processed)
        await async_session.flush()
        await record_mentions(
            async_session, processed_article_id=processed.id, surface_forms=[supplier]
        )

    await async_session.commit()


async def _titles_for(session: AsyncSession, watched: list[str]) -> list[str]:
    await PreferenceManager.create_or_update_preference(
        session, user_id="buyer", preferred_suppliers=watched
    )
    feed, *_ = await PersonalizationPipeline.generate_feed(
        session, user_id="buyer", limit=10, days_back=3650
    )
    return [
        (await session.get(NewsArticleProcessed, row.processed_article_id)).normalized_title
        for row in feed
    ]


async def test_short_form_watch_receives_the_full_legal_name(
    async_session: AsyncSession, corpus
) -> None:
    """The miss this phase started from."""
    titles = await _titles_for(async_session, ["Siemens"])

    assert "Siemens AG halts a plant" in titles


async def test_watching_a_parent_does_not_deliver_its_spinoff(
    async_session: AsyncSession, corpus
) -> None:
    """The parent's name is a prefix of the spinoff's, which text matching cannot separate."""
    titles = await _titles_for(async_session, ["Siemens"])

    assert not any("Siemens Energy" in title for title in titles)


async def test_an_unregistered_supplier_still_reaches_the_feed(
    async_session: AsyncSession, corpus
) -> None:
    """Nobody stops receiving news because their supplier is not in the registry yet."""
    titles = await _titles_for(async_session, ["Obscure Parts Ltd"])

    assert titles == ["Obscure Parts Ltd reports a fire"]


async def test_preferences_record_the_typed_text_and_the_resolved_identity(
    async_session: AsyncSession, corpus
) -> None:
    preference = await PreferenceManager.create_or_update_preference(
        async_session, user_id="buyer", preferred_suppliers=["Siemens"]
    )

    assert preference.preferred_suppliers == ["Siemens"]
    assert len(preference.preferred_supplier_ids) == 1
