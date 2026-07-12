"""Risk event endpoints."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import RiskEvent, UserNewsPreference
from procuresignal.personalization.matcher import PreferenceMatcher
from procuresignal.risk_events.taxonomy import risk_terms_for
from procuresignal.signals.taxonomy import normalize_signal_term
from sqlalchemy import String, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.risk_event import RiskEventItem, RiskEventResponse, RiskEventStatusUpdate
from api.translation import translate_risk_events

router = APIRouter(prefix="/api/risk-events", tags=["risk-events"])

RISK_EVENT_RETENTION_DAYS = 14


@router.get("", response_model=RiskEventResponse)
async def list_risk_events(
    user_id: str = Query(..., min_length=1, max_length=100),
    risk_type: str | None = Query(None),
    severity: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    supplier: str | None = Query(None),
    location: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> RiskEventResponse:
    """List procurement risk events."""

    cutoff = datetime.utcnow() - timedelta(days=RISK_EVENT_RETENTION_DAYS)
    stmt = _apply_filters(select(RiskEvent), risk_type, severity, status_filter).where(
        RiskEvent.published_at >= cutoff
    )
    stmt = _apply_json_filters(stmt, supplier, location, category)
    total_count = await session.scalar(select(func.count()).select_from(stmt.subquery()))

    preference = await session.scalar(
        select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
    )
    rank_score = _rank_score_expression(preference)
    rows = (
        await session.execute(
            stmt.add_columns(rank_score)
            .order_by(desc(rank_score), desc(RiskEvent.published_at), desc(RiskEvent.id))
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [_to_item(event, float(score)) for event, score in rows]
    items = await translate_risk_events(items, language)

    return RiskEventResponse(
        user_id=user_id,
        events=items,
        total_count=total_count or 0,
        generated_at=datetime.utcnow(),
    )


@router.get("/{risk_event_id}", response_model=RiskEventItem)
async def get_risk_event(
    risk_event_id: int,
    language: str = Query("en", min_length=2, max_length=10),
    session: AsyncSession = Depends(get_session),
) -> RiskEventItem:
    """Get a single procurement risk event."""

    event = await session.get(RiskEvent, risk_event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk event not found")
    translated = await translate_risk_events([_to_item(event, event.confidence)], language)
    return translated[0]


@router.patch("/{risk_event_id}/status", response_model=RiskEventItem)
async def update_risk_event_status(
    risk_event_id: int,
    payload: RiskEventStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> RiskEventItem:
    """Update a risk event's review status."""

    event = await session.get(RiskEvent, risk_event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk event not found")
    event.status = payload.status
    await session.commit()
    await session.refresh(event)
    return _to_item(event, event.confidence)


def _apply_filters(stmt, risk_type, severity, status_filter):
    if risk_type:
        stmt = stmt.where(RiskEvent.risk_type == risk_type)
    if severity:
        stmt = stmt.where(RiskEvent.severity == severity)
    if status_filter:
        stmt = stmt.where(RiskEvent.status == status_filter)
    return stmt


def _apply_json_filters(stmt, supplier, location, category):
    for column, expected in (
        (RiskEvent.affected_suppliers, supplier),
        (RiskEvent.affected_locations, location),
        (RiskEvent.affected_categories, category),
    ):
        if expected and expected.strip():
            stmt = stmt.where(_json_contains(column, expected))
    return stmt


def _json_contains(column, expected: str):
    normalized = _escape_like(normalize_signal_term(expected))
    return func.lower(cast(column, String)).like(f'%"{normalized}"%', escape="\\")


def _json_matches_any(column, values: set[str]):
    return or_(*(_json_contains(column, value) for value in sorted(values)))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rank_score_expression(preference: UserNewsPreference | None):
    score = RiskEvent.confidence
    if preference is None:
        return score.label("rank_score")

    suppliers = PreferenceMatcher._preferred_suppliers(preference)
    regions = PreferenceMatcher._preferred_regions(preference)
    categories = PreferenceMatcher._preferred_categories(preference)
    risk_types = risk_terms_for(PreferenceMatcher._preferred_signals(preference))
    if suppliers:
        score = score + case(
            (_json_matches_any(RiskEvent.affected_suppliers, suppliers), 0.15), else_=0.0
        )
    if regions:
        score = score + case(
            (_json_matches_any(RiskEvent.affected_locations, regions), 0.15), else_=0.0
        )
    if categories:
        score = score + case(
            (_json_matches_any(RiskEvent.affected_categories, categories), 0.1), else_=0.0
        )
    if risk_types:
        score = score + case((RiskEvent.risk_type.in_(risk_types), 0.1), else_=0.0)
    return case((score > 1.0, 1.0), else_=score).label("rank_score")


def _to_item(event: RiskEvent, rank_score: float) -> RiskEventItem:
    return RiskEventItem(
        id=event.id,
        processed_article_id=event.processed_article_id,
        risk_type=event.risk_type,
        severity=event.severity,
        confidence=event.confidence,
        affected_suppliers=event.affected_suppliers or [],
        affected_locations=event.affected_locations or [],
        affected_categories=event.affected_categories or [],
        evidence_snippet=event.evidence_snippet,
        recommendation=event.recommendation,
        source_name=event.source_name,
        source_url=event.source_url,
        published_at=event.published_at,
        status=event.status,
        rank_score=rank_score,
    )
