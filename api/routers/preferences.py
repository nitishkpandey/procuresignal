"""User preference endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.personalization import PreferenceManager
from procuresignal.personalization.categories import canonical_category_list
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.preference import (
    PreferenceBulkResponse,
    PreferenceBulkUpdate,
    PreferenceLanguageUpdate,
    PreferenceResponse,
    PreferenceUpdate,
)

router = APIRouter(prefix="/api", tags=["preferences"])


def _to_response(pref: Any) -> PreferenceResponse:
    return PreferenceResponse(
        user_id=pref.user_id,
        interested_categories=canonical_category_list(
            getattr(pref, "preferred_categories", []) or []
        ),
        interested_suppliers=list(getattr(pref, "preferred_suppliers", []) or []),
        interested_regions=list(getattr(pref, "preferred_regions", []) or []),
        interested_signals=list(getattr(pref, "preferred_signals", []) or []),
        excluded_categories=canonical_category_list(getattr(pref, "excluded_categories", []) or []),
        excluded_suppliers=list(getattr(pref, "excluded_suppliers", []) or []),
        excluded_regions=list(getattr(pref, "excluded_regions", []) or []),
        excluded_signals=list(getattr(pref, "excluded_signals", []) or []),
        platform_language=getattr(pref, "platform_language", "en") or "en",
        created_at=getattr(pref, "created_at", None),
        updated_at=getattr(pref, "updated_at", None),
    )


@router.post("/preferences", response_model=PreferenceResponse)
async def update_preferences(
    preference_update: PreferenceUpdate,
    session: AsyncSession = Depends(get_session),
) -> PreferenceResponse:
    """Create or update a user's preferences."""

    pref = await PreferenceManager.create_or_update_preference(
        session=session,
        user_id=preference_update.user_id,
        preferred_categories=preference_update.interested_categories,
        preferred_suppliers=preference_update.interested_suppliers,
        preferred_regions=preference_update.interested_regions,
        preferred_signals=preference_update.interested_signals,
        excluded_categories=preference_update.excluded_categories,
        excluded_suppliers=preference_update.excluded_suppliers,
        excluded_regions=preference_update.excluded_regions,
        excluded_signals=preference_update.excluded_signals,
        platform_language=preference_update.platform_language,
    )

    return _to_response(pref)


@router.patch("/preferences/language", response_model=PreferenceResponse)
async def update_preference_language(
    language_update: PreferenceLanguageUpdate,
    session: AsyncSession = Depends(get_session),
) -> PreferenceResponse:
    """Update only the platform language without invalidating feed rows."""

    pref = await PreferenceManager.update_platform_language(
        session=session,
        user_id=language_update.user_id,
        platform_language=language_update.platform_language,
    )
    return _to_response(pref)


@router.get("/preferences", response_model=PreferenceResponse)
async def get_preferences(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> PreferenceResponse:
    """Get a user's preferences."""

    pref = await PreferenceManager.get_preference(session, user_id)
    if not pref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preferences not found")

    return _to_response(pref)


@router.post("/preferences/bulk", response_model=PreferenceBulkResponse)
async def bulk_update_preferences(
    payload: PreferenceBulkUpdate,
    session: AsyncSession = Depends(get_session),
) -> PreferenceBulkResponse:
    """Create or update multiple user preference records."""

    updated_preferences: list[PreferenceResponse] = []
    for preference_update in payload.items:
        pref = await PreferenceManager.create_or_update_preference(
            session=session,
            user_id=preference_update.user_id,
            preferred_categories=preference_update.interested_categories,
            preferred_suppliers=preference_update.interested_suppliers,
            preferred_regions=preference_update.interested_regions,
            preferred_signals=preference_update.interested_signals,
            excluded_categories=preference_update.excluded_categories,
            excluded_suppliers=preference_update.excluded_suppliers,
            excluded_regions=preference_update.excluded_regions,
            excluded_signals=preference_update.excluded_signals,
            platform_language=preference_update.platform_language,
        )
        updated_preferences.append(_to_response(pref))

    return PreferenceBulkResponse(
        updated_count=len(updated_preferences),
        preferences=updated_preferences,
    )
