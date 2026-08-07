"""Watchlist endpoints.

Watching a supplier is ordinary procurement work, so it needs a member rather than an
admin. What it does need is a hard organization boundary: a watchlist is the team's,
and Phase 4's alerting keys off it.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import AuditLog, Base, Membership, Organization, Role, User
from procuresignal.suppliers.registry import register_supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup() -> dict:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with maker() as session:
            built = {}
            for index, (slug, email) in enumerate(
                [("acme", "buyer@acme.com"), ("globex", "buyer@globex.com")], start=1
            ):
                organization = Organization(public_id=f"org-{index}", name=slug.title(), slug=slug)
                user = User(public_id=f"user-{index}", email=email, password_hash="x")
                session.add_all([organization, user])
                await session.flush()
                session.add(
                    Membership(user_id=user.id, organization_id=organization.id, role=Role.MEMBER)
                )
                built[slug] = (organization, user)

            siemens = await register_supplier(session, canonical_name="Siemens AG")
            bosch = await register_supplier(session, canonical_name="Robert Bosch GmbH")
            await session.commit()
            built["suppliers"] = (siemens.public_id, bosch.public_id)
            return built

    built = asyncio.run(_setup())

    async def _session():
        async with maker() as session:
            yield session

    identity = {"slug": "acme", "role": Role.MEMBER}

    def _current_user() -> AuthenticatedUser:
        organization, user = built[identity["slug"]]
        return AuthenticatedUser(
            id=user.id,
            public_id=user.public_id,
            email=user.email,
            organization_id=organization.id,
            organization_public_id=organization.public_id,
            role=identity["role"],
        )

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = _current_user

    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.identity = identity  # type: ignore[attr-defined]
        test_client.suppliers = built["suppliers"]  # type: ignore[attr-defined]
        test_client.session_maker = maker  # type: ignore[attr-defined]
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def as_globex(client: TestClient) -> None:
    client.identity["slug"] = "globex"  # type: ignore[attr-defined]


def as_acme(client: TestClient) -> None:
    client.identity["slug"] = "acme"  # type: ignore[attr-defined]


def create(client: TestClient, name: str = "Tier 1") -> dict:
    response = client.post("/api/watchlists", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


# --- access ----------------------------------------------------------------------


def test_watchlists_require_authentication(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)

    assert client.get("/api/watchlists").status_code == 401
    assert client.post("/api/watchlists", json={"name": "x"}).status_code == 401


def test_a_viewer_may_read_but_not_change(client: TestClient) -> None:
    """Reading the team's list is fine; changing what alerts is not."""
    watchlist = create(client)
    client.identity["role"] = Role.VIEWER  # type: ignore[attr-defined]

    assert client.get("/api/watchlists").status_code == 200
    assert client.post("/api/watchlists", json={"name": "New"}).status_code == 403
    assert (
        client.post(
            f"/api/watchlists/{watchlist['public_id']}/suppliers/{client.suppliers[0]}"
        ).status_code
        == 403
    )


# --- organization boundary -------------------------------------------------------


def test_another_organizations_watchlist_is_not_visible(client: TestClient) -> None:
    create(client, "Acme Tier 1")
    as_globex(client)

    assert client.get("/api/watchlists").json()["items"] == []


def test_another_organizations_watchlist_is_404_not_403(client: TestClient) -> None:
    """403 would confirm the id exists, which is how ids get enumerated."""
    watchlist = create(client)
    as_globex(client)

    assert client.get(f"/api/watchlists/{watchlist['public_id']}").status_code == 404
    assert (
        client.post(
            f"/api/watchlists/{watchlist['public_id']}/suppliers/{client.suppliers[0]}"
        ).status_code
        == 404
    )


def test_two_organizations_may_both_have_a_tier_1(client: TestClient) -> None:
    create(client, "Tier 1")
    as_globex(client)

    assert client.post("/api/watchlists", json={"name": "Tier 1"}).status_code == 201


# --- behaviour -------------------------------------------------------------------


def test_a_duplicate_name_is_a_conflict_naming_the_existing_list(client: TestClient) -> None:
    create(client, "Tier 1")

    response = client.post("/api/watchlists", json={"name": "  tier 1 "})

    assert response.status_code == 409
    assert "Tier 1" in response.text


def test_adding_and_removing_a_supplier(client: TestClient) -> None:
    watchlist = create(client)
    siemens, _ = client.suppliers  # type: ignore[attr-defined]

    assert (
        client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}").status_code
        == 201
    )

    detail = client.get(f"/api/watchlists/{watchlist['public_id']}").json()
    assert [s["public_id"] for s in detail["suppliers"]] == [siemens]

    assert (
        client.delete(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}").status_code
        == 204
    )
    assert client.get(f"/api/watchlists/{watchlist['public_id']}").json()["suppliers"] == []


def test_adding_the_same_supplier_twice_is_harmless(client: TestClient) -> None:
    watchlist = create(client)
    siemens, _ = client.suppliers  # type: ignore[attr-defined]

    client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}")
    client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}")

    assert len(client.get(f"/api/watchlists/{watchlist['public_id']}").json()["suppliers"]) == 1


def test_an_unknown_supplier_is_404(client: TestClient) -> None:
    watchlist = create(client)

    assert (
        client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/nope").status_code == 404
    )


def test_the_detail_view_names_the_suppliers(client: TestClient) -> None:
    """A list of opaque ids is not something a buyer can check."""
    watchlist = create(client)
    siemens, _ = client.suppliers  # type: ignore[attr-defined]
    client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}")

    detail = client.get(f"/api/watchlists/{watchlist['public_id']}").json()
    assert detail["suppliers"][0]["canonical_name"] == "Siemens AG"


# --- audit -----------------------------------------------------------------------


def test_changes_to_what_alerts_are_audited(client: TestClient) -> None:
    watchlist = create(client)
    siemens, _ = client.suppliers  # type: ignore[attr-defined]
    client.post(f"/api/watchlists/{watchlist['public_id']}/suppliers/{siemens}")

    async def _rows():
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            return list((await session.execute(select(AuditLog))).scalars().all())

    actions = {(row.action, row.outcome) for row in asyncio.run(_rows())}
    assert ("watchlist.create", "success") in actions
    assert ("watchlist.supplier_added", "success") in actions
