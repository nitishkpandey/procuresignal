"""Tests for retention policy jobs."""

import asyncio
from datetime import datetime, timedelta

from procuresignal.jobs.retention import RetentionPolicy, prune_expired_records
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw, UserNewsFeed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _session_maker():
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


def test_prune_expired_records_is_idempotent():
    maker = _session_maker()
    now = datetime.utcnow()

    async def run():
        async with maker() as session:
            old_raw = NewsArticleRaw(
                provider="newsapi",
                provider_article_id="old",
                query_group="general",
                ingest_hash="old-raw",
                title="Old raw",
                description=None,
                content_snippet=None,
                article_url="https://example.com/old",
                canonical_url="https://example.com/old",
                source_name="Example",
                source_url=None,
                published_at=now - timedelta(days=20),
                language="en",
                ingested_at=now - timedelta(days=20),
            )
            recent_raw = NewsArticleRaw(
                provider="newsapi",
                provider_article_id="recent",
                query_group="general",
                ingest_hash="recent-raw",
                title="Recent raw",
                description=None,
                content_snippet=None,
                article_url="https://example.com/recent",
                canonical_url="https://example.com/recent",
                source_name="Example",
                source_url=None,
                published_at=now,
                language="en",
                ingested_at=now,
            )
            session.add_all([old_raw, recent_raw])
            await session.flush()
            old_processed = NewsArticleProcessed(
                raw_article_id=old_raw.id,
                normalized_title="Old processed",
                summary="Old processed summary",
                top_level_category="general",
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_suppliers=[],
                detected_categories=["general"],
                signal_score=0.5,
                processing_status="completed",
                llm_model="test",
                language="en",
                processed_at=now - timedelta(days=40),
            )
            recent_processed = NewsArticleProcessed(
                raw_article_id=recent_raw.id,
                normalized_title="Recent processed",
                summary="Recent processed summary",
                top_level_category="general",
                signal_tags=[],
                priority_signal=None,
                detected_regions=[],
                detected_suppliers=[],
                detected_categories=["general"],
                signal_score=0.5,
                processing_status="completed",
                llm_model="test",
                language="en",
                processed_at=now,
            )
            session.add_all([old_processed, recent_processed])
            await session.flush()
            session.add_all(
                [
                    UserNewsFeed(
                        user_id="u1",
                        processed_article_id=old_processed.id,
                        top_level_category="general",
                        rank_score=0.5,
                        match_reasons={},
                        surfaced_at=now - timedelta(days=20),
                    ),
                    UserNewsFeed(
                        user_id="u1",
                        processed_article_id=recent_processed.id,
                        top_level_category="general",
                        rank_score=0.5,
                        match_reasons={},
                        surfaced_at=now,
                    ),
                ]
            )
            await session.commit()

            policy = RetentionPolicy(raw_days=14, processed_days=30, feed_days=14)
            first = await prune_expired_records(session, policy=policy, now=now)
            second = await prune_expired_records(session, policy=policy, now=now)

            raw_count = await session.scalar(select(func.count()).select_from(NewsArticleRaw))
            processed_count = await session.scalar(
                select(func.count()).select_from(NewsArticleProcessed)
            )
            feed_count = await session.scalar(select(func.count()).select_from(UserNewsFeed))
            return first, second, raw_count, processed_count, feed_count

    first, second, raw_count, processed_count, feed_count = asyncio.run(run())

    assert first.raw_deleted == 1
    assert first.processed_deleted == 1
    assert first.feed_deleted == 1
    assert second.raw_deleted == 0
    assert second.processed_deleted == 0
    assert second.feed_deleted == 0
    assert raw_count == 1
    assert processed_count == 1
    assert feed_count == 1
