"""Relevance feedback endpoints.

Submitting feedback is ordinary use of the product, so a member can do it. Reading
everyone's queries back is an administrative act over personal data — query text is
user-entered content tied to an identified person — so the export requires an admin and
is scoped to the caller's organization.
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.auth.audit import record_audit
from procuresignal.models import NewsArticleProcessed, Role, SearchFeedback
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    AuthenticatedUser,
    ClientContext,
    get_client_context,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas.search_feedback import (
    SearchFeedbackCreate,
    SearchFeedbackItem,
    SearchFeedbackListResponse,
    SearchFeedbackRecorded,
)

router = APIRouter(
    prefix="/api/search", tags=["search-feedback"], dependencies=[Depends(get_current_user)]
)

_MEMBER = Depends(require_role(Role.MEMBER))
_ADMIN = Depends(require_role(Role.ADMIN))


def fingerprint(query: str) -> str:
    """A stable identifier for "the same query".

    Case and spacing are not what a user meant to vary, so "Port  Strike" and
    "port strike" group together. Anything finer would split every query into groups too
    small to learn anything from.
    """

    normalized = " ".join(query.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@router.post(
    "/feedback",
    response_model=SearchFeedbackRecorded,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MEMBER],
)
async def record_feedback(
    payload: SearchFeedbackCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> SearchFeedbackRecorded:
    """Record what a user did with a search result.

    Repeating a signal is a no-op rather than a conflict: a double-click is one label,
    and returning an error for it would make the UI report a failure for something the
    user did on purpose.
    """

    article = await session.get(NewsArticleProcessed, payload.article_id)
    if article is None:
        # An unchecked id fills the table with labels no ranker can use and no reviewer
        # can trace to anything.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    digest = fingerprint(payload.query)
    dialect = session.bind.dialect.name if session.bind else ""
    insert = postgresql_insert if dialect == "postgresql" else sqlite_insert

    # Deduplicated in the database rather than by reading first and then writing: two
    # clicks racing each other would both see no row and both insert.
    await session.execute(
        insert(SearchFeedback).values(
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            query_text=payload.query,
            query_fingerprint=digest,
            processed_article_id=payload.article_id,
            rank_position=payload.rank_position,
            signal=payload.signal,
            mode=payload.mode,
        )
        # By columns rather than by constraint name: the SQLite dialect's
        # on_conflict_do_nothing takes index_elements only, and development runs there.
        .on_conflict_do_nothing(
            index_elements=["user_id", "query_fingerprint", "processed_article_id", "signal"]
        )
    )

    # The fingerprint, not the query text. The text is already stored once in a table
    # Phase 7 knows to erase; copying it into the append-only audit log would put the
    # same personal data somewhere erasure deliberately cannot reach.
    await record_audit(
        session,
        action="search.feedback",
        outcome="success",
        actor=current_user,
        resource_type="search_feedback",
        resource_id=digest,
        detail={
            "article_id": payload.article_id,
            "rank_position": payload.rank_position,
            "signal": payload.signal,
            "mode": payload.mode,
        },
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return SearchFeedbackRecorded(recorded=True, query_fingerprint=digest)


@router.get("/feedback", response_model=SearchFeedbackListResponse, dependencies=[_ADMIN])
async def export_feedback(
    limit: int = Query(500, ge=1, le=5000),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SearchFeedbackListResponse:
    """Export this organization's feedback, newest first.

    Scoped to the caller's organization. Query text is personal data, and one tenant
    reading another's is a breach rather than a reporting bug.
    """

    rows = (
        (
            await session.execute(
                select(SearchFeedback)
                .where(SearchFeedback.organization_id == current_user.organization_id)
                .order_by(SearchFeedback.created_at.desc(), SearchFeedback.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = await session.scalar(
        select(func.count())
        .select_from(SearchFeedback)
        .where(SearchFeedback.organization_id == current_user.organization_id)
    )

    return SearchFeedbackListResponse(
        items=[
            SearchFeedbackItem(
                user_id=row.user_id,
                query_text=row.query_text,
                query_fingerprint=row.query_fingerprint,
                article_id=row.processed_article_id,
                rank_position=row.rank_position,
                signal=row.signal,
                mode=row.mode,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=int(total or 0),
    )
