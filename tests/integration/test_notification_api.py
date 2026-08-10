"""Notification and alert-rule endpoints, plus in-app delivery.

This is where an alert first becomes something a person can see. Until now the outbox
filled and nothing drained it.
"""

import asyncio
from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import (
    Base,
    Membership,
    Notification,
    Organization,
    RiskEvent,
    Role,
    User,
)
from procuresignal.notifications.outbox import enqueue_matches, pending_notifications
from procuresignal.notifications.rules import RuleMatch, create_alert_rule
from procuresignal.notifications.transports.in_app import InAppTransport, deliver_pending
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
            for index, slug in enumerate(("acme", "globex"), start=1):
                organization = Organization(public_id=f"org-{index}", name=slug.title(), slug=slug)
                user = User(public_id=f"user-{index}", email=f"buyer@{slug}.com", password_hash="x")
                session.add_all([organization, user])
                await session.flush()
                session.add(
                    Membership(user_id=user.id, organization_id=organization.id, role=Role.MEMBER)
                )
                built[slug] = (organization, user)

            supplier = await register_supplier(session, canonical_name="Siemens AG")
            event = RiskEvent(
                event_key="k1",
                processed_article_id=1,
                risk_type="supply_disruption",
                severity="high",
                confidence=0.9,
                affected_suppliers=["Siemens AG"],
                affected_supplier_ids=[supplier.public_id],
                affected_locations=[],
                affected_categories=["logistics"],
                evidence_snippet="A plant halted.",
                recommendation="Review exposure.",
                source_name="Wire",
                source_url="https://example.test/1",
                published_at=datetime(2026, 8, 1),
                status="new",
            )
            session.add(event)

            # One queued alert for acme only.
            rule = await create_alert_rule(
                session, organization_id=built["acme"][0].id, name="Tier 1"
            )
            await session.flush()
            await enqueue_matches(
                session,
                matches=[
                    RuleMatch(rule=rule, event=event, supplier_public_ids=[supplier.public_id])
                ],
            )
            await session.commit()
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
        test_client.session_maker = maker  # type: ignore[attr-defined]
        yield test_client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


# --- in-app delivery -------------------------------------------------------------


async def _drain(client: TestClient) -> int:
    async with client.session_maker() as session:  # type: ignore[attr-defined]
        delivered = await deliver_pending(session, transport=InAppTransport())
        await session.commit()
        return delivered


def test_draining_marks_queued_alerts_delivered(client: TestClient) -> None:
    assert asyncio.run(_drain(client)) == 1

    async def _pending():
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            return await pending_notifications(session)

    assert asyncio.run(_pending()) == []


def test_a_failing_transport_leaves_the_alert_queued(client: TestClient) -> None:
    """At-least-once: the alert must survive a transport that is having a bad day."""

    class _Broken:
        name = "broken"

        async def deliver(self, notification) -> None:  # noqa: ANN001
            raise RuntimeError("nope")

    async def _run():
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            delivered = await deliver_pending(session, transport=_Broken())
            await session.commit()
            still = await pending_notifications(session)
            return delivered, len(still)

    delivered, still_pending = asyncio.run(_run())
    assert delivered == 0
    assert still_pending == 1


def test_one_failure_does_not_stop_the_rest_of_the_drain(client: TestClient) -> None:
    """A single poisonous notification must not block the queue behind it."""

    class _FailsFirst:
        name = "flaky"

        def __init__(self) -> None:
            self.seen = 0

        async def deliver(self, notification) -> None:  # noqa: ANN001
            self.seen += 1
            if self.seen == 1:
                raise RuntimeError("first one fails")

    async def _run():
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            rows = (await session.execute(select(Notification))).scalars().all()
            # Queue a second alert for the same recipient via a different rule.
            second_rule = await create_alert_rule(
                session, organization_id=rows[0].organization_id, name="Second"
            )
            await session.flush()
            event = (await session.execute(select(RiskEvent))).scalars().one()
            await enqueue_matches(
                session,
                matches=[RuleMatch(rule=second_rule, event=event, supplier_public_ids=["s"])],
            )
            await session.commit()

            transport = _FailsFirst()
            delivered = await deliver_pending(session, transport=transport)
            await session.commit()
            return delivered, transport.seen

    delivered, attempted = asyncio.run(_run())
    assert attempted == 2, "the drain stopped at the first failure"
    assert delivered == 1


# --- the notification feed -------------------------------------------------------


def test_notifications_require_authentication(client: TestClient) -> None:
    app.dependency_overrides.pop(get_current_user)

    assert client.get("/api/notifications").status_code == 401


def test_a_user_sees_their_own_alerts(client: TestClient) -> None:
    asyncio.run(_drain(client))

    body = client.get("/api/notifications").json()
    assert body["total_count"] == 1
    assert "Siemens AG" in body["items"][0]["subject"]
    assert body["unread_count"] == 1


def test_another_organization_sees_nothing_of_ours(client: TestClient) -> None:
    asyncio.run(_drain(client))
    client.identity["slug"] = "globex"  # type: ignore[attr-defined]

    assert client.get("/api/notifications").json()["items"] == []


def test_undelivered_alerts_are_not_shown(client: TestClient) -> None:
    """A queued alert is owed, not yet sent; showing it would double-notify."""
    assert client.get("/api/notifications").json()["items"] == []


def test_marking_read_clears_the_unread_count(client: TestClient) -> None:
    asyncio.run(_drain(client))
    public_id = client.get("/api/notifications").json()["items"][0]["public_id"]

    assert client.post(f"/api/notifications/{public_id}/read").status_code == 204
    assert client.get("/api/notifications").json()["unread_count"] == 0


def test_marking_someone_elses_notification_read_is_404(client: TestClient) -> None:
    asyncio.run(_drain(client))
    public_id = client.get("/api/notifications").json()["items"][0]["public_id"]
    client.identity["slug"] = "globex"  # type: ignore[attr-defined]

    assert client.post(f"/api/notifications/{public_id}/read").status_code == 404


def test_the_alert_carries_why_it_was_sent(client: TestClient) -> None:
    asyncio.run(_drain(client))

    item = client.get("/api/notifications").json()["items"][0]
    assert item["rule_name"] == "Tier 1"
    assert item["risk_type"] == "supply_disruption"
    assert item["severity"] == "high"


# --- alert rules -----------------------------------------------------------------


def test_members_may_manage_alert_rules(client: TestClient) -> None:
    created = client.post(
        "/api/alert-rules",
        json={"name": "Sanctions only", "min_severity": "critical", "risk_types": ["sanctions"]},
    )
    assert created.status_code == 201

    names = [r["name"] for r in client.get("/api/alert-rules").json()["items"]]
    assert "Sanctions only" in names


def test_a_viewer_may_not_change_what_alerts(client: TestClient) -> None:
    client.identity["role"] = Role.VIEWER  # type: ignore[attr-defined]

    assert client.get("/api/alert-rules").status_code == 200
    assert client.post("/api/alert-rules", json={"name": "x"}).status_code == 403


def test_an_invalid_severity_is_rejected_with_the_options(client: TestClient) -> None:
    response = client.post("/api/alert-rules", json={"name": "x", "min_severity": "urgent"})

    assert response.status_code in (400, 422)
    assert "severity" in response.text.lower()


def test_rules_are_scoped_to_the_organization(client: TestClient) -> None:
    client.identity["slug"] = "globex"  # type: ignore[attr-defined]

    assert client.get("/api/alert-rules").json()["items"] == []
