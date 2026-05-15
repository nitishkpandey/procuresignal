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
        interested_categories: Optional[List[str]] = None,
        interested_suppliers: Optional[List[str]] = None,
        interested_regions: Optional[List[str]] = None,
        interested_signals: Optional[List[str]] = None,
        excluded_categories: Optional[List[str]] = None,
        excluded_suppliers: Optional[List[str]] = None,
        excluded_regions: Optional[List[str]] = None,
        excluded_signals: Optional[List[str]] = None,
    ) -> UserNewsPreference:
        """Create or update user preference.

        Args:
            session: Database session
            user_id: User ID
            interested_categories: Categories user wants
            interested_suppliers: Suppliers to watch
            interested_regions: Regions to monitor
            interested_signals: Signals to track
            excluded_categories: Categories to exclude
            excluded_suppliers: Suppliers to exclude
            excluded_regions: Regions to exclude
            excluded_signals: Signals to exclude

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
            if interested_categories is not None:
                pref.interested_categories = interested_categories
            if interested_suppliers is not None:
                pref.interested_suppliers = interested_suppliers
            if interested_regions is not None:
                pref.interested_regions = interested_regions
            if interested_signals is not None:
                pref.interested_signals = interested_signals
            if excluded_categories is not None:
                pref.excluded_categories = excluded_categories
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
                interested_categories=interested_categories or [],
                interested_suppliers=interested_suppliers or [],
                interested_regions=interested_regions or [],
                interested_signals=interested_signals or [],
                excluded_categories=excluded_categories or [],
                excluded_suppliers=excluded_suppliers or [],
                excluded_regions=excluded_regions or [],
                excluded_signals=excluded_signals or [],
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
