"""Tests for organization-scoped supplier watchlists.

Scoped to the organization rather than the user: a procurement team watches a supplier
together, and per-user lists fragment exactly the thing they are trying to share.
Entries reference canonical suppliers, because a free-text watchlist would reinherit
every miss Phase 2 removed.
"""

import pytest
from procuresignal.models import Membership, Organization, Role, Supplier, User, Watchlist
from procuresignal.suppliers.registry import register_supplier
from procuresignal.watchlists.service import (
    DuplicateWatchlistError,
    add_supplier,
    create_watchlist,
    list_watchlists,
    remove_supplier,
    watched_supplier_ids,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def org(async_session: AsyncSession):
    organization = Organization(public_id="org-1", name="Acme", slug="acme")
    user = User(public_id="user-1", email="buyer@acme.com", password_hash="x")
    async_session.add_all([organization, user])
    await async_session.flush()
    async_session.add(
        Membership(user_id=user.id, organization_id=organization.id, role=Role.MEMBER)
    )
    await async_session.flush()
    return organization, user


@pytest.fixture
async def other_org(async_session: AsyncSession):
    organization = Organization(public_id="org-2", name="Globex", slug="globex")
    async_session.add(organization)
    await async_session.flush()
    return organization


@pytest.fixture
async def siemens(async_session: AsyncSession) -> Supplier:
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()
    return supplier


async def test_a_watchlist_belongs_to_an_organization(async_session, org) -> None:
    organization, user = org
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()

    assert watchlist.organization_id == organization.id
    assert watchlist.public_id


async def test_two_organizations_may_use_the_same_name(async_session, org, other_org) -> None:
    """ "Tier 1" is what everybody calls it; it must not be globally unique."""
    organization, user = org
    await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await create_watchlist(
        async_session, organization_id=other_org.id, name="Tier 1", created_by_user_id=None
    )
    await async_session.flush()

    assert len((await async_session.execute(select(Watchlist))).scalars().all()) == 2


async def test_one_organization_cannot_have_two_lists_with_one_name(async_session, org) -> None:
    """Otherwise a team has two "Tier 1" lists and cannot tell which one alerts."""
    organization, user = org
    await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()

    with pytest.raises(DuplicateWatchlistError):
        await create_watchlist(
            async_session,
            organization_id=organization.id,
            name="  tier 1  ",
            created_by_user_id=user.id,
        )


async def test_adding_a_supplier_twice_is_harmless(async_session, org, siemens) -> None:
    organization, user = org
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()

    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await async_session.flush()

    assert await watched_supplier_ids(async_session, organization_id=organization.id) == {
        siemens.public_id
    }


async def test_removing_a_supplier_stops_it_being_watched(async_session, org, siemens) -> None:
    organization, user = org
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await async_session.flush()

    await remove_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await async_session.flush()

    assert await watched_supplier_ids(async_session, organization_id=organization.id) == set()


async def test_watched_ids_cover_every_list_in_the_organization(
    async_session, org, siemens
) -> None:
    """Rule evaluation joins against this once; per-list queries would make it N+1."""
    organization, user = org
    bosch = await register_supplier(async_session, canonical_name="Robert Bosch GmbH")

    first = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    second = await create_watchlist(
        async_session, organization_id=organization.id, name="Logistics", created_by_user_id=user.id
    )
    await async_session.flush()

    await add_supplier(async_session, watchlist_id=first.id, supplier_id=siemens.id)
    await add_supplier(async_session, watchlist_id=second.id, supplier_id=bosch.id)
    await async_session.flush()

    assert await watched_supplier_ids(async_session, organization_id=organization.id) == {
        siemens.public_id,
        bosch.public_id,
    }


async def test_another_organization_watches_nothing_of_ours(
    async_session, org, other_org, siemens
) -> None:
    organization, user = org
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    await async_session.flush()

    assert await watched_supplier_ids(async_session, organization_id=other_org.id) == set()


async def test_an_inactive_supplier_is_not_reported_as_watched(async_session, org, siemens) -> None:
    """A merged-away supplier must stop alerting under its old identity."""
    organization, user = org
    watchlist = await create_watchlist(
        async_session, organization_id=organization.id, name="Tier 1", created_by_user_id=user.id
    )
    await async_session.flush()
    await add_supplier(async_session, watchlist_id=watchlist.id, supplier_id=siemens.id)
    siemens.is_active = False
    await async_session.flush()

    assert await watched_supplier_ids(async_session, organization_id=organization.id) == set()


async def test_listing_returns_only_this_organizations_lists(async_session, org, other_org) -> None:
    organization, user = org
    await create_watchlist(
        async_session, organization_id=organization.id, name="Ours", created_by_user_id=user.id
    )
    await create_watchlist(
        async_session, organization_id=other_org.id, name="Theirs", created_by_user_id=None
    )
    await async_session.flush()

    names = [w.name for w in await list_watchlists(async_session, organization_id=organization.id)]
    assert names == ["Ours"]
