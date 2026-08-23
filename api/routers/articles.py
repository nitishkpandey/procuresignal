"""Article endpoints."""

from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw, UserNewsFeed
from procuresignal.observability.metrics import record_search
from procuresignal.search.embeddings import embedding_provider
from procuresignal.search.hybrid import ScoredHit, search
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.article_entities import (
    categories_for_response,
    regions_for_response,
    suppliers_for_response,
)
from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.schemas.article import ArticleDetail, ArticleReadResponse, SearchResponse, SearchResult
from api.translation import translate_article_detail, translate_search_results

router = APIRouter(prefix="/api", tags=["articles"], dependencies=[Depends(get_current_user)])


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
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    """Get a single article's full details."""

    processed = await session.get(NewsArticleProcessed, article_id)
    if not processed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    raw = await session.get(NewsArticleRaw, processed.raw_article_id)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    return await translate_article_detail(_build_article_detail(processed, raw), language)


@router.post("/articles/{article_id}/read", response_model=ArticleReadResponse)
async def mark_article_read(
    article_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ArticleReadResponse:
    """Mark an article as read for the authenticated user."""

    user_id = current_user.public_id
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


async def _results_for(session: AsyncSession, hits: list[ScoredHit]) -> list[SearchResult]:
    """Load the articles behind the hits, in the order retrieval ranked them.

    `relevance` is the fused score scaled against the best result for this query.
    Reciprocal rank scores are small absolute numbers — a first-place result scores
    about 0.016 — and are only ever meaningful relative to the other results for the
    same query, so showing them raw would be showing noise.
    """

    if not hits:
        return []

    rows = (
        await session.execute(
            select(NewsArticleProcessed, NewsArticleRaw)
            .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
            .where(NewsArticleProcessed.id.in_([hit.processed_id for hit in hits]))
        )
    ).all()
    by_id = {processed.id: (processed, raw) for processed, raw in rows}
    best = max(hit.score for hit in hits) or 1.0

    results = []
    for hit in hits:
        found = by_id.get(hit.processed_id)
        if found is None:
            # Retrieval and this query ran in the same transaction, so this means the
            # article was pruned between them. Dropping it beats a half-empty card.
            continue
        processed, raw = found
        results.append(
            SearchResult(
                id=processed.id,
                title=processed.normalized_title,
                summary=processed.summary,
                category=processed.top_level_category,
                published_at=raw.published_at,
                relevance=min(1.0, hit.score / best),
            )
        )
    return results


@router.get("/search", response_model=SearchResponse)
async def search_articles(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(7, ge=1, le=30),
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """Search processed articles, lexically and semantically."""

    start = perf_counter()
    outcome = await search(
        session,
        query=q,
        limit=limit,
        days=days,
        provider=embedding_provider(),
        language=language,
    )
    results = await translate_search_results(await _results_for(session, outcome.hits), language)
    elapsed = perf_counter() - start
    record_search(outcome.mode, elapsed)

    return SearchResponse(
        query=q,
        total_results=len(results),
        results=results,
        search_time_ms=elapsed * 1000,
        mode=outcome.mode,
    )
