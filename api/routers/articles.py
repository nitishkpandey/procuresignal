"""Article endpoints."""

from datetime import datetime, timedelta
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, UserNewsFeed
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.article_entities import (
    categories_for_response,
    regions_for_response,
    suppliers_for_response,
)
from api.dependencies import get_session
from api.schemas.article import ArticleDetail, ArticleReadResponse, SearchResponse, SearchResult

router = APIRouter(prefix="/api", tags=["articles"])


def _build_article_detail(processed: NewsArticleProcessed, raw: NewsArticleRaw) -> ArticleDetail:
    return ArticleDetail(
        id=processed.id,
        title=processed.normalized_title,
        summary=processed.summary,
        description=raw.description,
        content_snippet=raw.content_snippet,
        category=processed.top_level_category,
        signal_tags=processed.signal_tags or [],
        priority_signal=processed.priority_signal,
        detected_suppliers=suppliers_for_response(processed, raw),
        detected_regions=regions_for_response(processed, raw),
        detected_categories=categories_for_response(processed),
        source_name=raw.source_name,
        source_url=raw.source_url or "",
        article_url=raw.article_url,
        published_at=raw.published_at,
        processed_at=processed.processed_at,
        language=processed.language,
        llm_model=processed.llm_model or "unknown",
    )


@router.get("/articles/{article_id}", response_model=ArticleDetail)
async def get_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    """Get a single article's full details."""

    processed = await session.get(NewsArticleProcessed, article_id)
    if not processed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    raw = await session.get(NewsArticleRaw, processed.raw_article_id)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    return _build_article_detail(processed, raw)


@router.post("/articles/{article_id}/read", response_model=ArticleReadResponse)
async def mark_article_read(
    article_id: int,
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ArticleReadResponse:
    """Mark an article as read for the given user."""

    result = await session.execute(
        select(UserNewsFeed).where(
            UserNewsFeed.user_id == user_id,
            UserNewsFeed.processed_article_id == article_id,
        )
    )
    feed_entry = result.scalar_one_or_none()
    if not feed_entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed entry not found")

    feed_entry.is_read = True
    await session.commit()

    return ArticleReadResponse(article_id=article_id, user_id=user_id, read=True)


def _score_search_result(query: str, processed: NewsArticleProcessed, raw: NewsArticleRaw) -> float:
    haystack = " ".join(
        part
        for part in [
            processed.normalized_title,
            processed.summary,
            raw.description or "",
            raw.content_snippet or "",
            raw.title,
        ]
        if part
    ).lower()
    normalized_query = query.strip().lower()
    terms = [term for term in normalized_query.split() if term]

    score = 0.0
    if normalized_query in haystack:
        score += 0.5

    score += min(0.3, 0.1 * sum(1 for term in terms if term in haystack))

    if normalized_query in raw.title.lower():
        score += 0.2

    return min(score, 1.0)


@router.get("/search", response_model=SearchResponse)
async def search_articles(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(7, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """Search processed articles."""

    start = perf_counter()
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = f"%{q.strip()}%"

    result = await session.execute(
        select(NewsArticleProcessed, NewsArticleRaw)
        .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
        .where(NewsArticleProcessed.processed_at >= cutoff_date)
        .where(
            or_(
                NewsArticleProcessed.normalized_title.ilike(query),
                NewsArticleProcessed.summary.ilike(query),
                NewsArticleRaw.title.ilike(query),
                NewsArticleRaw.description.ilike(query),
                NewsArticleRaw.content_snippet.ilike(query),
            )
        )
        .order_by(desc(NewsArticleProcessed.processed_at))
        .limit(limit * 3)
    )

    scored_results = []
    for processed, raw in result.all():
        relevance = _score_search_result(q, processed, raw)
        if relevance > 0:
            scored_results.append(
                SearchResult(
                    id=processed.id,
                    title=processed.normalized_title,
                    summary=processed.summary,
                    category=processed.top_level_category,
                    published_at=raw.published_at,
                    relevance=relevance,
                )
            )

    scored_results.sort(key=lambda result: result.relevance, reverse=True)
    results = scored_results[:limit]

    return SearchResponse(
        query=q,
        total_results=len(scored_results),
        results=results,
        search_time_ms=(perf_counter() - start) * 1000,
    )
