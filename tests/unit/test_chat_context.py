"""Tests for the chat context builder."""

import asyncio
from datetime import datetime

from procuresignal.chat.context import build_system_prompt
from procuresignal.models import (
    Base,
    NewsArticleProcessed,
    NewsArticleRaw,
    UserNewsFeed,
    UserNewsPreference,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _make_session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return asyncio.run(setup())


def test_prompt_without_preferences_is_generic():
    maker = _make_session_maker()

    async def run():
        async with maker() as session:
            return await build_system_prompt(session, "nobody")

    prompt = asyncio.run(run())
    assert "procurement" in prompt.lower()
    assert isinstance(prompt, str) and len(prompt) > 0


def test_prompt_includes_preferences_and_articles():
    maker = _make_session_maker()

    async def run():
        async with maker() as session:
            raw = NewsArticleRaw(
                provider="newsapi",
                provider_article_id="a1",
                query_group="supplier_risk",
                ingest_hash="h1",
                title="Bosch strike in Poland",
                description="d",
                content_snippet="c",
                article_url="https://e.com/a",
                canonical_url="https://e.com/a",
                source_name="Reuters",
                source_url="https://reuters.com",
                published_at=datetime.utcnow(),
                language="en",
                ingested_at=datetime.utcnow(),
            )
            session.add(raw)
            await session.flush()
            processed = NewsArticleProcessed(
                raw_article_id=raw.id,
                normalized_title="Bosch strike Poland",
                summary="Workers at Bosch began a strike.",
                top_level_category="automotive",
                signal_tags=["strike"],
                priority_signal="strike",
                detected_regions=["Poland"],
                detected_suppliers=["Bosch"],
                detected_categories=["automotive"],
                signal_score=0.9,
                processing_status="completed",
                llm_model="test",
                language="en",
                processed_at=datetime.utcnow(),
            )
            session.add(processed)
            await session.flush()
            session.add(
                UserNewsFeed(
                    user_id="u1",
                    processed_article_id=processed.id,
                    top_level_category="automotive",
                    rank_score=0.9,
                    match_reasons={},
                    surfaced_at=datetime.utcnow(),
                )
            )
            session.add(
                UserNewsPreference(
                    user_id="u1",
                    preferred_categories=["automotive"],
                    preferred_suppliers=["Bosch"],
                    preferred_regions=["Poland"],
                    preferred_signals=["strike"],
                    excluded_categories=[],
                    excluded_suppliers=[],
                    excluded_regions=[],
                    excluded_signals=[],
                    excluded_topics=[],
                    onboarding_completed=True,
                )
            )
            await session.commit()
            return await build_system_prompt(session, "u1")

    prompt = asyncio.run(run())
    assert "Bosch" in prompt
    assert "Bosch strike Poland" in prompt
    assert "strike" in prompt
