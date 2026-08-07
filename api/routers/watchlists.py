"""Watchlist endpoints.

Watching a supplier is ordinary procurement work, so a member can do it. What is not
ordinary is seeing another organization's list, so every lookup is scoped to the
caller's organization and a miss is a 404.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from procuresignal.auth.audit import record_audit
from procuresignal.models import Role, Supplier, Watchlist, WatchlistEntry
from procuresignal.watchlists.service import (
    DuplicateWatchlistError,
    WatchlistError,
    add_supplier,
    create_watchlist,
    list_watchlists,
    remove_supplier,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    AuthenticatedUser,
    ClientContext,
    get_client_context,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas.watchlist import (
    WatchedSupplier,
    WatchlistCreate,
    WatchlistDetail,
    WatchlistListResponse,
    WatchlistSummary,
)

router = APIRouter(
    prefix="/api/watchlists", tags=["watchlists"], dependencies=[Depends(get_current_user)]
)

_MEMBER = Depends(require_role(Role.MEMBER))


async def _owned(
    session: AsyncSession, public_id: str, current_user: AuthenticatedUser
) -> Watchlist:
    """Fetch a watchlist belonging to the caller's organization.

    404 rather than 403 for someone else's: a 403 confirms the id exists, which is how
    ids get enumerated.
    """

    watchlist = (
        await session.execute(
            select(Watchlist)
            .where(Watchlist.public_id == public_id)
            .where(Watchlist.organization_id == current_user.organization_id)
        )
    ).scalar_one_or_none()
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return watchlist


async def _supplier(session: AsyncSession, public_id: str) -> Supplier:
    supplier = (
        await session.execute(
            select(Supplier)
            .where(Supplier.public_id == public_id)
            .where(Supplier.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


@router.get("", response_model=WatchlistListResponse)
async def list_all(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistListResponse:
    """The caller's organization's watchlists, with how many suppliers each holds."""

    watchlists = await list_watchlists(session, organization_id=current_user.organization_id)

    # One grouped count for every list, rather than a query per row.
    rows = (
        await session.execute(
            select(WatchlistEntry.watchlist_id, func.count(WatchlistEntry.id))
            .where(WatchlistEntry.watchlist_id.in_([w.id for w in watchlists] or [0]))
            .group_by(WatchlistEntry.watchlist_id)
        )
    ).all()
    counts: dict[int, int] = {int(watchlist_id): int(total) for watchlist_id, total in rows}

    items = [
        WatchlistSummary(
            public_id=w.public_id,
            name=w.name,
            supplier_count=int(counts.get(w.id, 0)),
            created_at=w.created_at,
        )
        for w in watchlists
    ]
    return WatchlistListResponse(items=items, total_count=len(items))


@router.get("/{public_id}", response_model=WatchlistDetail)
async def detail(
    public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistDetail:
    watchlist = await _owned(session, public_id, current_user)

    suppliers = (
        (
            await session.execute(
                select(Supplier)
                .join(WatchlistEntry, WatchlistEntry.supplier_id == Supplier.id)
                .where(WatchlistEntry.watchlist_id == watchlist.id)
                .where(Supplier.is_active.is_(True))
                .order_by(Supplier.canonical_name)
            )
        )
        .scalars()
        .all()
    )

    return WatchlistDetail(
        public_id=watchlist.public_id,
        name=watchlist.name,
        suppliers=[WatchedSupplier.model_validate(s) for s in suppliers],
        created_at=watchlist.created_at,
    )


@router.post(
    "", response_model=WatchlistSummary, status_code=status.HTTP_201_CREATED, dependencies=[_MEMBER]
)
async def create(
    payload: WatchlistCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> WatchlistSummary:
    try:
        watchlist = await create_watchlist(
            session,
            organization_id=current_user.organization_id,
            name=payload.name,
            created_by_user_id=current_user.id,
        )
    except DuplicateWatchlistError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except WatchlistError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    await record_audit(
        session,
        action="watchlist.create",
        outcome="success",
        actor=current_user,
        resource_type="watchlist",
        resource_id=watchlist.public_id,
        detail={"name": watchlist.name},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return WatchlistSummary(
        public_id=watchlist.public_id,
        name=watchlist.name,
        supplier_count=0,
        created_at=watchlist.created_at,
    )


@router.post(
    "/{public_id}/suppliers/{supplier_public_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MEMBER],
)
async def watch(
    public_id: str,
    supplier_public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Watch a supplier. Watching one already watched is a no-op, not an error."""

    watchlist = await _owned(session, public_id, current_user)
    supplier = await _supplier(session, supplier_public_id)

    await add_supplier(
        session,
        watchlist_id=watchlist.id,
        supplier_id=supplier.id,
        added_by_user_id=current_user.id,
    )
    await record_audit(
        session,
        action="watchlist.supplier_added",
        outcome="success",
        actor=current_user,
        resource_type="watchlist",
        resource_id=watchlist.public_id,
        detail={"supplier": supplier.public_id, "supplier_name": supplier.canonical_name},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
    return {"status": "watching", "supplier": supplier.public_id}


@router.delete(
    "/{public_id}/suppliers/{supplier_public_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MEMBER],
)
async def unwatch(
    public_id: str,
    supplier_public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    watchlist = await _owned(session, public_id, current_user)
    supplier = await _supplier(session, supplier_public_id)

    await remove_supplier(session, watchlist_id=watchlist.id, supplier_id=supplier.id)
    await record_audit(
        session,
        action="watchlist.supplier_removed",
        outcome="success",
        actor=current_user,
        resource_type="watchlist",
        resource_id=watchlist.public_id,
        detail={"supplier": supplier.public_id},
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()
