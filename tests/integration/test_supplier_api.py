"""Admin endpoints for correcting supplier identity.

Without these a wrong or missing resolution is unfixable, and an entity-resolution
system nobody can correct gets abandoned.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import ArticleSupplierMention, AuditLog, Base, Role, Supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_current_user, get_session
from api.main import app
from tests.conftest import fixed_identity


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    async def _session():
        async with maker() as session:
            yield session

    role = {"current": Role.ADMIN}
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: fixed_identity("u1", role=role["current"])

    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.role = role  # type: ignore[attr-defined]
        test_client.session_maker = maker  # type: ignore[attr-defined]
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def as_member(client: TestClient) -> None:
    client.role["current"] = Role.MEMBER  # type: ignore[attr-defined]


def create(client: TestClient, name: str, **extra) -> dict:
    response = client.post("/api/suppliers", json={"canonical_name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


# --- authorization ---------------------------------------------------------------


def test_every_route_requires_authentication(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)

    assert client.get("/api/suppliers").status_code == 401
    assert client.post("/api/suppliers", json={"canonical_name": "X"}).status_code == 401
    assert client.get("/api/suppliers/unresolved").status_code == 401


def test_reading_suppliers_only_needs_a_member(client: TestClient) -> None:
    create(client, "Siemens AG")
    as_member(client)

    assert client.get("/api/suppliers").status_code == 200
    assert client.get("/api/suppliers/unresolved").status_code == 200


def test_changing_the_registry_requires_an_admin(client: TestClient) -> None:
    """Supplier identity decides what sanctions screening matches."""
    existing = create(client, "Siemens AG")
    as_member(client)

    assert client.post("/api/suppliers", json={"canonical_name": "New Co"}).status_code == 403
    assert (
        client.post(
            f"/api/suppliers/{existing['public_id']}/aliases", json={"alias": "Siemens"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/suppliers/{existing['public_id']}/merge",
            json={"merge_public_id": "whatever"},
        ).status_code
        == 403
    )


# --- registering -----------------------------------------------------------------


def test_creating_a_supplier_returns_it_with_a_public_id(client: TestClient) -> None:
    body = create(client, "Siemens AG", country="DE")

    assert body["canonical_name"] == "Siemens AG"
    assert body["country"] == "DE"
    assert body["public_id"]
    assert body["is_active"] is True


def test_the_same_name_twice_is_a_conflict(client: TestClient) -> None:
    create(client, "Siemens AG")

    response = client.post("/api/suppliers", json={"canonical_name": "  siemens  ag "})

    assert response.status_code == 409
    assert "Siemens AG" in response.text


def test_a_conflicting_alias_names_the_supplier_that_holds_it(client: TestClient) -> None:
    """The operator has to know which supplier to look at."""
    create(client, "Apple Inc")
    second = create(client, "Apple Bank")

    response = client.post(f"/api/suppliers/{second['public_id']}/aliases", json={"alias": "Apple"})

    assert response.status_code == 409
    assert "Apple Inc" in response.text


def test_adding_an_alias_makes_the_name_resolve(client: TestClient) -> None:
    supplier = create(client, "Robert Bosch GmbH")

    added = client.post(f"/api/suppliers/{supplier['public_id']}/aliases", json={"alias": "Bosch"})
    assert added.status_code == 201

    listed = client.get("/api/suppliers", params={"q": "Bosch"}).json()
    assert [row["public_id"] for row in listed["items"]] == [supplier["public_id"]]


def test_aliases_for_an_unknown_supplier_are_404(client: TestClient) -> None:
    response = client.post("/api/suppliers/does-not-exist/aliases", json={"alias": "X"})

    assert response.status_code == 404


# --- merging ---------------------------------------------------------------------


def test_merging_folds_one_supplier_into_another(client: TestClient) -> None:
    keep = create(client, "Siemens AG")
    duplicate = create(client, "Siemens Aktiengesellschaft")

    response = client.post(
        f"/api/suppliers/{keep['public_id']}/merge",
        json={"merge_public_id": duplicate["public_id"]},
    )

    assert response.status_code == 200
    listed = client.get("/api/suppliers").json()
    assert [row["public_id"] for row in listed["items"]] == [keep["public_id"]]


def test_merging_a_supplier_into_itself_is_refused(client: TestClient) -> None:
    supplier = create(client, "Siemens AG")

    response = client.post(
        f"/api/suppliers/{supplier['public_id']}/merge",
        json={"merge_public_id": supplier["public_id"]},
    )

    assert response.status_code == 400


# --- the unresolved queue --------------------------------------------------------


def test_unresolved_queue_ranks_by_how_often_a_name_appears(client: TestClient) -> None:
    """This is the work queue that turns a coverage number into a list."""

    async def _seed() -> None:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            for article_id, name in [
                (1, "Frequent Unknown Ltd"),
                (2, "Frequent Unknown Ltd"),
                (3, "Frequent Unknown Ltd"),
                (4, "Rare Unknown Ltd"),
            ]:
                session.add(
                    ArticleSupplierMention(
                        processed_article_id=article_id,
                        supplier_id=None,
                        surface_form=name,
                        confidence=0.0,
                    )
                )
            await session.commit()

    asyncio.run(_seed())

    body = client.get("/api/suppliers/unresolved").json()

    assert body["items"][0]["surface_form"] == "Frequent Unknown Ltd"
    assert body["items"][0]["mention_count"] == 3
    assert body["items"][1]["mention_count"] == 1


def test_resolved_mentions_are_not_in_the_queue(client: TestClient) -> None:
    supplier = create(client, "Siemens AG")

    async def _seed() -> None:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            row = (
                await session.execute(
                    select(Supplier).where(Supplier.public_id == supplier["public_id"])
                )
            ).scalar_one()
            session.add(
                ArticleSupplierMention(
                    processed_article_id=1,
                    supplier_id=row.id,
                    surface_form="Siemens AG",
                    confidence=1.0,
                )
            )
            await session.commit()

    asyncio.run(_seed())

    assert client.get("/api/suppliers/unresolved").json()["items"] == []


def test_unresolved_is_not_mistaken_for_a_supplier_id(client: TestClient) -> None:
    """A literal path segment must win over the wildcard beside it."""
    assert client.get("/api/suppliers/unresolved").status_code == 200


# --- audit -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "call"),
    [
        ("supplier.create", lambda c: c.post("/api/suppliers", json={"canonical_name": "Audited"})),
    ],
)
def test_registry_changes_are_audited(client: TestClient, action: str, call) -> None:
    """Changing supplier identity changes what sanctions screening matches."""
    call(client)

    async def _rows():
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            return list((await session.execute(select(AuditLog))).scalars().all())

    recorded = {(row.action, row.outcome) for row in asyncio.run(_rows())}
    assert (action, "success") in recorded
