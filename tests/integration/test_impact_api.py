"""Impact endpoints over a watchlist.

The scoring arithmetic is covered by property tests. What matters here is who sees what:
the list is one organization's watched suppliers and nobody else's, and the number never
arrives without the events behind it.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import (
    Base,
    Membership,
    Organization,
    RiskEvent,
    Role,
    Supplier,
    User,
    Watchlist,
    WatchlistEntry,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.main import app


@pytest.fixture()
def impact_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        identities = {}
        async with maker() as session:
            now = datetime.utcnow()

            suppliers = {}
            for slug, name in [
                ("acme-parts", "Acme Parts GmbH"),
                ("quiet-co", "Quiet Components Ltd"),
                ("designated", "Designated Machine Tools OOO"),
            ]:
                supplier = Supplier(
                    public_id=slug,
                    canonical_name=name,
                    normalized_name=slug.replace("-", " "),
                    country="DE",
                    is_active=True,
                )
                session.add(supplier)
                await session.flush()
                suppliers[slug] = supplier

            session.add_all(
                [
                    RiskEvent(
                        event_key="acme-strike",
                        processed_article_id=1,
                        risk_type="strike",
                        severity="medium",
                        confidence=0.8,
                        affected_suppliers=["Acme Parts"],
                        affected_supplier_ids=["acme-parts"],
                        affected_locations=["Germany"],
                        affected_categories=["automotive"],
                        evidence_snippet="Workers at the Stuttgart plant walked out.",
                        recommendation="Review buffers.",
                        source_name="Reuters",
                        published_at=now - timedelta(days=1),
                        status="new",
                    ),
                    RiskEvent(
                        event_key="acme-bankruptcy",
                        processed_article_id=2,
                        risk_type="bankruptcy",
                        severity="critical",
                        confidence=0.9,
                        affected_suppliers=["Acme Parts"],
                        affected_supplier_ids=["acme-parts"],
                        affected_locations=["Germany"],
                        affected_categories=["automotive"],
                        evidence_snippet="The group filed for protection from creditors.",
                        recommendation="Review continuity.",
                        source_name="Handelsblatt",
                        published_at=now - timedelta(days=2),
                        status="new",
                    ),
                    RiskEvent(
                        event_key="designated-sanctions",
                        processed_article_id=3,
                        risk_type="sanctions",
                        severity="low",
                        confidence=0.2,
                        affected_suppliers=["Designated Machine Tools"],
                        affected_supplier_ids=["designated"],
                        affected_locations=["Russia"],
                        affected_categories=["machinery"],
                        evidence_snippet="Added to the consolidated designations list.",
                        recommendation="Review compliance exposure.",
                        source_name="Official Journal",
                        published_at=now - timedelta(days=12),
                        status="new",
                    ),
                ]
            )

            for slug, watched in [("acme", ["acme-parts", "quiet-co"]), ("globex", [])]:
                organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
                session.add(organization)
                await session.flush()
                user = User(public_id=f"user-{slug}", email=f"buyer@{slug}.example", is_active=True)
                session.add(user)
                await session.flush()
                session.add(
                    Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN)
                )
                watchlist = Watchlist(
                    public_id=f"wl-{slug}",
                    organization_id=organization.id,
                    name="Tier 1",
                    normalized_name="tier 1",
                    created_by_user_id=user.id,
                )
                session.add(watchlist)
                await session.flush()
                for supplier_slug in watched:
                    session.add(
                        WatchlistEntry(
                            watchlist_id=watchlist.id,
                            supplier_id=suppliers[supplier_slug].id,
                            added_by_user_id=user.id,
                        )
                    )
                identities[slug] = AuthenticatedUser(
                    id=user.id,
                    public_id=user.public_id,
                    email=user.email,
                    organization_id=organization.id,
                    organization_public_id=organization.public_id,
                    role=Role.ADMIN,
                )

            await session.commit()
        return maker, identities

    maker, identities = asyncio.run(prepare())
    caller = {"identity": identities["acme"]}

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: caller["identity"]

    with TestClient(app) as client:
        yield client, caller, identities

    app.dependency_overrides.clear()


def test_the_list_covers_what_this_organization_watches(impact_env) -> None:
    client, _caller, _identities = impact_env

    payload = client.get("/api/impact").json()

    assert payload["total"] == 2
    assert {item["supplier_public_id"] for item in payload["items"]} == {
        "acme-parts",
        "quiet-co",
    }


def test_the_most_exposed_supplier_comes_first(impact_env) -> None:
    """The ordering is the product: a buyer opens this screen to find out where to look,
    not to read an alphabetical list."""

    client, _caller, _identities = impact_env

    items = client.get("/api/impact").json()["items"]

    assert items[0]["supplier_public_id"] == "acme-parts"
    assert items[0]["value"] > items[1]["value"]


def test_a_watched_supplier_with_no_news_scores_zero(impact_env) -> None:
    """Present in the list, plainly at zero. Omitting quiet suppliers would make an
    empty row indistinguishable from one nobody is watching."""

    client, _caller, _identities = impact_env

    quiet = next(
        item
        for item in client.get("/api/impact").json()["items"]
        if item["supplier_public_id"] == "quiet-co"
    )

    assert quiet["value"] == 0.0
    assert quiet["band"] == "none"
    assert quiet["drivers"] == []


def test_the_number_never_arrives_without_its_evidence(impact_env) -> None:
    """A procurement decision defended with an unexplainable number is not defensible.
    Every driver names the event, the source and the snippet behind it."""

    client, _caller, _identities = impact_env

    acme = client.get("/api/impact/acme-parts").json()

    assert acme["value"] > 0
    assert len(acme["drivers"]) == 2
    top = acme["drivers"][0]
    assert top["event_key"] == "acme-bankruptcy", "drivers are ranked by contribution"
    assert top["source_name"] == "Handelsblatt"
    assert top["evidence_snippet"]
    assert acme["drivers"][0]["contribution"] >= acme["drivers"][1]["contribution"]


def test_a_designated_supplier_is_in_the_top_band(impact_env) -> None:
    """Low severity, low confidence, twelve days old — and still severe, because a
    sanctions match is a compliance stop rather than a point on a gradient."""

    client, _caller, _identities = impact_env

    designated = client.get("/api/impact/designated").json()

    assert designated["band"] == "severe"
    assert designated["value"] < 0.1, "the band is floored, the arithmetic is not faked"


def test_an_unwatched_supplier_can_still_be_checked(impact_env) -> None:
    """Checking exposure before deciding whether to watch is the obvious use. The
    registry and its risk events are global read-only data."""

    client, _caller, _identities = impact_env

    response = client.get("/api/impact/designated")

    assert response.status_code == 200
    assert "designated" not in {
        item["supplier_public_id"] for item in client.get("/api/impact").json()["items"]
    }


def test_another_organizations_watchlist_is_not_visible(impact_env) -> None:
    client, caller, identities = impact_env

    caller["identity"] = identities["globex"]
    payload = client.get("/api/impact").json()

    assert payload["items"] == []
    assert payload["total"] == 0


def test_an_unknown_supplier_is_a_404(impact_env) -> None:
    client, _caller, _identities = impact_env

    assert client.get("/api/impact/no-such-supplier").status_code == 404
