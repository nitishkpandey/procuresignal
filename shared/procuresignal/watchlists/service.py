"""Create and maintain watchlists."""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Supplier, Watchlist, WatchlistEntry
from procuresignal.suppliers.normalization import normalize


class WatchlistError(Exception):
    """Base class for watchlist rejections."""


class DuplicateWatchlistError(WatchlistError):
    """This organization already has a list by that name."""


async def create_watchlist(
    session: AsyncSession,
    *,
    organization_id: int,
    name: str,
    created_by_user_id: int | None = None,
) -> Watchlist:
    """Create a named watchlist for an organization."""

    normalized = normalize(name)
    if not normalized:
        raise WatchlistError("a watchlist needs a name")

    existing = (
        await session.execute(
            select(Watchlist)
            .where(Watchlist.organization_id == organization_id)
            .where(Watchlist.normalized_name == normalized)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateWatchlistError(f"'{existing.name}' already exists in this organization")

    watchlist = Watchlist(
        public_id=uuid4().hex,
        organization_id=organization_id,
        name=name.strip(),
        normalized_name=normalized,
        created_by_user_id=created_by_user_id,
    )
    session.add(watchlist)
    await session.flush()
    return watchlist


async def list_watchlists(session: AsyncSession, *, organization_id: int) -> list[Watchlist]:
    return list(
        (
            await session.execute(
                select(Watchlist)
                .where(Watchlist.organization_id == organization_id)
                .order_by(Watchlist.name)
            )
        )
        .scalars()
        .all()
    )


async def add_supplier(
    session: AsyncSession,
    *,
    watchlist_id: int,
    supplier_id: int,
    added_by_user_id: int | None = None,
) -> None:
    """Watch a supplier. Adding one already present is a no-op."""

    existing = (
        await session.execute(
            select(WatchlistEntry)
            .where(WatchlistEntry.watchlist_id == watchlist_id)
            .where(WatchlistEntry.supplier_id == supplier_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    session.add(
        WatchlistEntry(
            watchlist_id=watchlist_id,
            supplier_id=supplier_id,
            added_by_user_id=added_by_user_id,
        )
    )
    await session.flush()


async def remove_supplier(session: AsyncSession, *, watchlist_id: int, supplier_id: int) -> None:
    await session.execute(
        delete(WatchlistEntry)
        .where(WatchlistEntry.watchlist_id == watchlist_id)
        .where(WatchlistEntry.supplier_id == supplier_id)
    )
    await session.flush()


async def watched_supplier_ids(session: AsyncSession, *, organization_id: int) -> set[str]:
    """Canonical suppliers this organization watches, across all of its lists.

    One query for the whole organization: rule evaluation joins against this, and asking
    per watchlist would make evaluation N+1 over rules.

    Inactive suppliers are excluded, so a merged-away one stops alerting under its old
    identity — the same rule resolution follows.
    """

    rows = (
        (
            await session.execute(
                select(Supplier.public_id)
                .join(WatchlistEntry, WatchlistEntry.supplier_id == Supplier.id)
                .join(Watchlist, Watchlist.id == WatchlistEntry.watchlist_id)
                .where(Watchlist.organization_id == organization_id)
                .where(Supplier.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return set(rows)
