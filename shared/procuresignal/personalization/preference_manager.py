"""User preference management."""

from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import UserNewsFeed, UserNewsPreference
from procuresignal.personalization.categories import canonical_category_list


class PreferenceManager:
    """Manage user preferences."""

    @staticmethod
    async def create_or_update_preference(
        session: AsyncSession,
        user_id: str,
        preferred_categories: Optional[List[str]] = None,
        preferred_suppliers: Optional[List[str]] = None,
        preferred_regions: Optional[List[str]] = None,
        preferred_signals: Optional[List[str]] = None,
        excluded_categories: Optional[List[str]] = None,
        excluded_suppliers: Optional[List[str]] = None,
        excluded_regions: Optional[List[str]] = None,
        excluded_signals: Optional[List[str]] = None,
        excluded_topics: Optional[List[str]] = None,
    ) -> UserNewsPreference:
        """Create or update user preference.

        Args:
            session: Database session
            user_id: User ID
            preferred_categories: Categories user wants
            preferred_suppliers: Suppliers to watch
            preferred_regions: Regions to monitor
            preferred_signals: Signals user wants
            excluded_categories: Categories to exclude
            excluded_suppliers: Suppliers to exclude
            excluded_regions: Regions to exclude
            excluded_signals: Signals to exclude
            excluded_topics: Topics to exclude

        Returns:
            Updated UserNewsPreference
        """
        if preferred_categories is not None:
            preferred_categories = canonical_category_list(preferred_categories)
        if excluded_categories is not None:
            excluded_categories = canonical_category_list(excluded_categories)
        if excluded_topics is not None:
            excluded_topics = canonical_category_list(excluded_topics)

        # Check if exists
        existing = await session.execute(
            select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
        )
        pref = existing.scalar_one_or_none()

        if pref:
            # Update existing
            if preferred_categories is not None:
                pref.preferred_categories = preferred_categories
            if preferred_suppliers is not None:
                pref.preferred_suppliers = preferred_suppliers
            if preferred_regions is not None:
                pref.preferred_regions = preferred_regions
            if preferred_signals is not None:
                pref.preferred_signals = preferred_signals
            if excluded_categories is not None:
                pref.excluded_categories = excluded_categories
                pref.excluded_topics = excluded_categories
            elif excluded_topics is not None:
                pref.excluded_categories = excluded_topics
                pref.excluded_topics = excluded_topics
            if excluded_suppliers is not None:
                pref.excluded_suppliers = excluded_suppliers
            if excluded_regions is not None:
                pref.excluded_regions = excluded_regions
            if excluded_signals is not None:
                pref.excluded_signals = excluded_signals
        else:
            # Create new
            pref = UserNewsPreference(
                user_id=user_id,
                preferred_categories=preferred_categories or [],
                preferred_suppliers=preferred_suppliers or [],
                preferred_regions=preferred_regions or [],
                preferred_signals=preferred_signals or [],
                excluded_categories=excluded_categories or excluded_topics or [],
                excluded_suppliers=excluded_suppliers or [],
                excluded_regions=excluded_regions or [],
                excluded_signals=excluded_signals or [],
                excluded_topics=excluded_topics or excluded_categories or [],
            )

        session.add(pref)
        await session.execute(delete(UserNewsFeed).where(UserNewsFeed.user_id == user_id))
        await session.commit()
        await session.refresh(pref)

        return pref

    @staticmethod
    async def get_preference(
        session: AsyncSession,
        user_id: str,
    ) -> Optional[UserNewsPreference]:
        """Get user preference.

        Args:
            session: Database session
            user_id: User ID

        Returns:
            UserNewsPreference or None
        """
        result = await session.execute(
            select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()
