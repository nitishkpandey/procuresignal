"""Risk event endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import RiskEvent, UserNewsPreference
from procuresignal.personalization.matcher import PreferenceMatcher
from procuresignal.risk_events.persistence import generate_risk_events
from procuresignal.risk_events.taxonomy import risk_terms_for
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.risk_event import RiskEventItem, RiskEventResponse, RiskEventStatusUpdate
from api.translation import translate_risk_events

router = APIRouter(prefix="/api/risk-events", tags=["risk-events"])


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

    await generate_risk_events(session, days_back=7, limit=500)
    stmt = _apply_filters(select(RiskEvent), risk_type, severity, status_filter)
    result = await session.execute(stmt.order_by(desc(RiskEvent.published_at)))
    all_events = list(result.scalars().all())

    preference = await session.scalar(
        select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
    )
    filtered = [
        event
        for event in all_events
        if _contains(event.affected_suppliers, supplier)
        and _contains(event.affected_locations, location)
        and _contains(event.affected_categories, category)
    ]
    ranked = sorted(
        filtered,
        key=lambda event: (_rank_score(event, preference), event.published_at, event.id),
        reverse=True,
    )
    page = ranked[offset : offset + limit]
    items = [_to_item(event, _rank_score(event, preference)) for event in page]
    items = await translate_risk_events(items, language)

    return RiskEventResponse(
        user_id=user_id,
        events=items,
        total_count=len(ranked),
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


def _contains(values: list[str], expected: str | None) -> bool:
    if not expected:
        return True
    expected_lower = expected.strip().lower()
    return any(expected_lower in value.lower() for value in values)


def _rank_score(event: RiskEvent, preference: UserNewsPreference | None) -> float:
    if preference is None:
        return event.confidence

    score = event.confidence
    if PreferenceMatcher._normalized(
        event.affected_suppliers
    ) & PreferenceMatcher._preferred_suppliers(preference):
        score += 0.15
    if PreferenceMatcher._region_tokens(
        event.affected_locations
    ) & PreferenceMatcher._preferred_regions(preference):
        score += 0.15
    if set(event.affected_categories or []) & PreferenceMatcher._preferred_categories(preference):
        score += 0.1
    if event.risk_type in risk_terms_for(PreferenceMatcher._preferred_signals(preference)):
        score += 0.1
    return min(score, 1.0)


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
