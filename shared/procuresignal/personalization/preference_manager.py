"""User preference management."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import UserNewsPreference


class PreferenceManager:
    """Manage user preferences."""

    @staticmethod
    async def create_or_update_preference(
        session: AsyncSession,
        user_id: str,
        preferred_categories: Optional[List[str]] = None,
        preferred_suppliers: Optional[List[str]] = None,
        preferred_regions: Optional[List[str]] = None,
        excluded_topics: Optional[List[str]] = None,
    ) -> UserNewsPreference:
        """Create or update user preference.

        Args:
            session: Database session
            user_id: User ID
            preferred_categories: Categories user wants
            preferred_suppliers: Suppliers to watch
            preferred_regions: Regions to monitor
            excluded_topics: Topics to exclude

        Returns:
            Updated UserNewsPreference
        """
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
            if excluded_topics is not None:
                pref.excluded_topics = excluded_topics
        else:
            # Create new
            pref = UserNewsPreference(
                user_id=user_id,
                preferred_categories=preferred_categories or [],
                preferred_suppliers=preferred_suppliers or [],
                preferred_regions=preferred_regions or [],
                excluded_topics=excluded_topics or [],
            )

        session.add(pref)
        await session.commit()

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
