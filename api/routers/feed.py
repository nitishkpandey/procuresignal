"""Feed endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, UserNewsFeed
from procuresignal.personalization import PersonalizationPipeline
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.feed import ArticleInFeed, FeedResponse

router = APIRouter(prefix="/api", tags=["feed"])


async def _load_feed_rows(
    session: AsyncSession,
    user_id: str,
    limit: int,
) -> list[tuple[UserNewsFeed, NewsArticleProcessed, NewsArticleRaw]]:
    stmt = (
        select(UserNewsFeed, NewsArticleProcessed, NewsArticleRaw)
        .join(NewsArticleProcessed, UserNewsFeed.processed_article_id == NewsArticleProcessed.id)
        .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
        .where(UserNewsFeed.user_id == user_id)
        .where(UserNewsFeed.is_hidden.is_(False))
        .order_by(desc(UserNewsFeed.rank_score), desc(UserNewsFeed.surfaced_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(feed_entry, processed, raw) for feed_entry, processed, raw in result.all()]


async def _count_feed_rows(session: AsyncSession, user_id: str) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(UserNewsFeed)
        .where(UserNewsFeed.user_id == user_id)
        .where(UserNewsFeed.is_hidden.is_(False))
    )
    return int(total or 0)


@router.get("/feed", response_model=FeedResponse)
async def get_personalized_feed(
    user_id: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    days: int = Query(7, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
) -> FeedResponse:
    """Get the user's personalized feed."""

    feed_rows = await _load_feed_rows(session, user_id=user_id, limit=limit)
    if not feed_rows:
        await PersonalizationPipeline.generate_feed(
            session=session,
            user_id=user_id,
            limit=limit,
            days_back=days,
        )
        feed_rows = await _load_feed_rows(session, user_id=user_id, limit=limit)

    articles = [
        ArticleInFeed(
            id=processed.id,
            title=processed.normalized_title,
            summary=processed.summary,
            category=processed.top_level_category,
            signal_tags=processed.signal_tags or [],
            priority_signal=processed.priority_signal,
            detected_suppliers=processed.detected_suppliers or [],
            detected_regions=processed.detected_regions or [],
            source_name=raw.source_name,
            published_at=raw.published_at,
            article_url=raw.article_url,
            relevance_score=feed_entry.rank_score,
            rank=index + 1,
        )
        for index, (feed_entry, processed, raw) in enumerate(feed_rows)
    ]

    return FeedResponse(
        user_id=user_id,
        articles=articles,
        total_count=await _count_feed_rows(session, user_id=user_id),
        generated_at=datetime.utcnow(),
        days_included=days,
    )
