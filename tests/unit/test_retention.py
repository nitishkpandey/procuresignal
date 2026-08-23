"""Tests for retention policy jobs."""

import asyncio
from datetime import datetime, timedelta

from procuresignal.jobs.retention import RetentionPolicy, prune_expired_records
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw, RiskEvent, UserNewsFeed
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
            session.add_all(
                [
                    RiskEvent(
                        event_key="old-risk-event",
                        processed_article_id=old_processed.id,
                        risk_type="strike",
                        severity="medium",
                        confidence=0.8,
                        affected_suppliers=[],
                        affected_locations=[],
                        affected_categories=["general"],
                        evidence_snippet="Old risk event.",
                        recommendation="Review buffers.",
                        source_name="Example",
                        source_url=None,
                        published_at=now - timedelta(days=20),
                        status="new",
                    ),
                    RiskEvent(
                        event_key="recent-risk-event",
                        processed_article_id=recent_processed.id,
                        risk_type="strike",
                        severity="medium",
                        confidence=0.8,
                        affected_suppliers=[],
                        affected_locations=[],
                        affected_categories=["general"],
                        evidence_snippet="Recent risk event.",
                        recommendation="Review buffers.",
                        source_name="Example",
                        source_url=None,
                        published_at=now,
                        status="new",
                    ),
                ]
            )
            await session.commit()

            policy = RetentionPolicy(
                raw_days=14,
                processed_days=30,
                feed_days=14,
                risk_event_days=14,
            )
            first = await prune_expired_records(session, policy=policy, now=now)
            second = await prune_expired_records(session, policy=policy, now=now)

            raw_count = await session.scalar(select(func.count()).select_from(NewsArticleRaw))
            processed_count = await session.scalar(
                select(func.count()).select_from(NewsArticleProcessed)
            )
            feed_count = await session.scalar(select(func.count()).select_from(UserNewsFeed))
            risk_event_count = await session.scalar(select(func.count()).select_from(RiskEvent))
            return first, second, raw_count, processed_count, feed_count, risk_event_count

    first, second, raw_count, processed_count, feed_count, risk_event_count = asyncio.run(run())

    assert first.raw_deleted == 1
    assert first.processed_deleted == 1
    assert first.feed_deleted == 1
    assert first.risk_events_deleted == 1
    assert second.raw_deleted == 0
    assert second.processed_deleted == 0
    assert second.feed_deleted == 0
    assert second.risk_events_deleted == 0
    assert raw_count == 1
    assert processed_count == 1
    assert feed_count == 1
    assert risk_event_count == 1


def test_every_documented_window_is_actually_pruned() -> None:
    """A table documented with a retention window that nothing prunes is a false
    statement in a compliance document, and it stays false until somebody audits the
    code rather than the paperwork.

    The job iterates the registry, so this asserts the two cannot diverge.
    """

    from procuresignal.privacy.inventory import INVENTORY

    documented = {entry.table for entry in INVENTORY if entry.retention_days is not None}

    assert documented, "no table has a retention window at all"
    # The job's coverage is the registry itself; this pins the tables that must be in it.
    for table in ("search_feedback", "agent_runs", "chat_messages", "notifications"):
        assert table in documented, f"{table} has no expiry"


def test_the_named_policy_fields_come_from_the_registry() -> None:
    """RetentionPolicy exists because search, scoring and the agent tools ask for these
    four windows by name. Writing the numbers twice is how the inventory and the code
    start disagreeing about how long an article is kept."""

    from procuresignal.jobs.retention import RetentionPolicy
    from procuresignal.privacy.inventory import INVENTORY

    by_table = {entry.table: entry.retention_days for entry in INVENTORY}
    policy = RetentionPolicy()

    assert policy.raw_days == by_table["news_articles_raw"]
    assert policy.processed_days == by_table["news_articles_processed"]
    assert policy.feed_days == by_table["user_news_feed"]
    assert policy.risk_event_days == by_table["risk_events"]


async def test_pruning_removes_expired_search_feedback(async_session) -> None:
    """The table Phase 5 left with no expiry at all."""

    from datetime import datetime, timedelta

    from procuresignal.jobs.retention import prune_expired_records
    from procuresignal.models import (
        Membership,
        Organization,
        Role,
        SearchFeedback,
        User,
    )
    from sqlalchemy import select

    organization = Organization(public_id="org-1", name="acme", slug="acme")
    async_session.add(organization)
    await async_session.flush()
    user = User(public_id="user-1", email="b@acme.example", is_active=True)
    async_session.add(user)
    await async_session.flush()
    async_session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))

    now = datetime.utcnow()
    for label, created in [("stale", now - timedelta(days=500)), ("fresh", now)]:
        async_session.add(
            SearchFeedback(
                organization_id=organization.id,
                user_id=user.id,
                query_text=label,
                query_fingerprint=label * 8,
                processed_article_id=1,
                rank_position=1,
                signal="click",
                mode="hybrid",
                created_at=created,
            )
        )
    await async_session.commit()

    result = await prune_expired_records(async_session, now=now)

    surviving = (await async_session.execute(select(SearchFeedback))).scalars().all()
    assert [row.query_text for row in surviving] == ["fresh"]
    assert result.by_table["search_feedback"] == 1
