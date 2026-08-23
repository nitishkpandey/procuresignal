"""Running an analysis, and deciding about what it proposed.

The split that matters: asking for an analysis is ordinary work, so a member can do it.
Approving a recommendation puts the organization's name behind an action, so it needs an
admin — the same line Phase 5 drew between giving search feedback and exporting everyone's
queries.

The decision is one-way and audited. An approval that can be quietly re-decided is not an
approval trail, and "who agreed to this" is the question this whole phase exists to be
able to answer a year later.
"""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.agents.client import AgentTurn, ToolCall
from procuresignal.models import (
    AgentRecommendation,
    AuditLog,
    Base,
    Membership,
    Organization,
    RiskEvent,
    Role,
    Supplier,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.main import app
from api.routers.agents import get_agent_client

ANALYSIS = (
    '{"findings": ["An unresolved strike."], "recommendations": ['
    '{"title": "Qualify a second source", "rationale": "The strike is open.",'
    ' "evidence_event_keys": ["acme-strike"]},'
    '{"title": "Hold new orders", "rationale": "Quality defect outstanding.",'
    ' "evidence_event_keys": ["acme-strike"]}]}'
)


class ScriptedClient:
    """Looks up the risk events, then answers with the contract.

    The tool call is not decoration. Citations are verified against what the tools
    actually returned during the run, so a client that answers without calling anything
    has no verified evidence and every recommendation is correctly discarded — which is
    exactly what this fixture did until it called a tool first.
    """

    name = "scripted-model"

    def __init__(self):
        self.turns = 0

    async def respond(self, *, instructions, input, tools):
        self.turns += 1
        if self.turns == 1:
            return AgentTurn(
                text=None,
                tool_calls=[
                    ToolCall(
                        call_id="c0",
                        name="list_risk_events",
                        arguments={"supplier_public_id": "acme-parts"},
                    )
                ],
                prompt_tokens=10,
                completion_tokens=5,
            )
        return AgentTurn(text=ANALYSIS, tool_calls=[], prompt_tokens=10, completion_tokens=5)


@pytest.fixture()
def agent_env(monkeypatch: pytest.MonkeyPatch):
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
        identities: dict[str, AuthenticatedUser] = {}
        async with maker() as session:
            session.add(
                Supplier(
                    public_id="acme-parts",
                    canonical_name="Acme Parts GmbH",
                    normalized_name="acme parts",
                    country="DE",
                    is_active=True,
                )
            )
            session.add(
                RiskEvent(
                    event_key="acme-strike",
                    processed_article_id=1,
                    risk_type="strike",
                    severity="medium",
                    confidence=0.8,
                    affected_suppliers=["Acme"],
                    affected_supplier_ids=["acme-parts"],
                    affected_locations=["Germany"],
                    affected_categories=["automotive"],
                    evidence_snippet="Workers walked out.",
                    recommendation="Review buffers.",
                    source_name="Reuters",
                    published_at=datetime.utcnow(),
                    status="new",
                )
            )
            for slug in ("acme", "globex"):
                organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
                session.add(organization)
                await session.flush()
                for role in (Role.ADMIN, Role.MEMBER):
                    user = User(
                        public_id=f"user-{slug}-{role.value}",
                        email=f"{role.value}@{slug}.example",
                        is_active=True,
                    )
                    session.add(user)
                    await session.flush()
                    session.add(
                        Membership(organization_id=organization.id, user_id=user.id, role=role)
                    )
                    identities[f"{slug}-{role.value}"] = AuthenticatedUser(
                        id=user.id,
                        public_id=user.public_id,
                        email=user.email,
                        organization_id=organization.id,
                        organization_public_id=organization.public_id,
                        role=role,
                    )
            await session.commit()
        return maker, identities

    maker, identities = asyncio.run(prepare())
    caller = {"identity": identities["acme-admin"]}
    client_holder: dict[str, object] = {"client": ScriptedClient()}

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: caller["identity"]
    app.dependency_overrides[get_agent_client] = lambda: client_holder["client"]

    with TestClient(app) as http:
        yield http, caller, identities, client_holder, maker

    app.dependency_overrides.clear()


def _start(http: TestClient):
    return http.post("/api/analyses", json={"supplier_public_id": "acme-parts"})


def test_a_member_can_ask_for_an_analysis(agent_env) -> None:
    """Ordinary procurement work. Requiring an admin to look at a supplier would put
    the feature behind the person least likely to be doing the sourcing."""

    http, caller, identities, _client, _maker = agent_env
    caller["identity"] = identities["acme-member"]

    response = _start(http)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["supplier_public_id"] == "acme-parts"
    assert body["public_id"]


def test_the_analysis_comes_back_with_its_transcript(agent_env) -> None:
    """The transcript is the audit trail. A recommendation nobody can trace back to the
    tool calls that produced it is not reviewable."""

    http, _caller, _identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]

    detail = http.get(f"/api/analyses/{public_id}").json()

    assert detail["model"] == "scripted-model"
    assert [step["kind"] for step in detail["steps"]] == [
        "tool_call",
        "tool_result",
        "model_message",
        "evidence_check",
    ]
    assert len(detail["recommendations"]) == 2
    assert detail["recommendations"][0]["status"] == "proposed"
    assert detail["recommendations"][0]["evidence_event_keys"] == ["acme-strike"]


def test_an_unknown_supplier_is_a_404(agent_env) -> None:
    http, _caller, _identities, _client, _maker = agent_env

    response = http.post("/api/analyses", json={"supplier_public_id": "no-such-supplier"})

    assert response.status_code == 404


def test_without_a_provider_the_endpoint_says_so(agent_env) -> None:
    """No fake analysis, ever — the same rule search follows when it has no embedding
    provider. A plausible answer generated without a model is the worst outcome here."""

    http, _caller, _identities, client_holder, _maker = agent_env
    client_holder["client"] = None

    response = _start(http)

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_a_member_cannot_approve(agent_env) -> None:
    """Approving puts the organization's name behind an action."""

    http, caller, identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]
    caller["identity"] = identities["acme-member"]

    response = http.post(
        f"/api/analyses/{public_id}/recommendations/0/approve", json={"note": "looks right"}
    )

    assert response.status_code == 403


def test_an_admin_can_approve_a_recommendation(agent_env) -> None:
    http, _caller, _identities, _client, maker = agent_env
    public_id = _start(http).json()["public_id"]

    response = http.post(
        f"/api/analyses/{public_id}/recommendations/0/approve",
        json={"note": "Agreed in the Tuesday review."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    async def stored():
        async with maker() as session:
            rows = await session.execute(
                select(AgentRecommendation).order_by(AgentRecommendation.ordinal)
            )
            return list(rows.scalars().all())

    rows = asyncio.run(stored())
    assert rows[0].status == "approved"
    assert rows[0].decision_note == "Agreed in the Tuesday review."
    assert rows[0].decided_at is not None
    # Rejecting one recommendation must not touch the others.
    assert rows[1].status == "proposed"


def test_an_admin_can_reject_a_recommendation(agent_env) -> None:
    http, _caller, _identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]

    response = http.post(
        f"/api/analyses/{public_id}/recommendations/1/reject",
        json={"note": "We already dual-source this."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_a_decision_cannot_be_quietly_re_made(agent_env) -> None:
    """One-way on purpose. An approval that can be reversed without a trace is not an
    approval trail — and a silent overwrite would leave the earlier decision nowhere."""

    http, _caller, _identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]
    http.post(f"/api/analyses/{public_id}/recommendations/0/approve", json={"note": "yes"})

    again = http.post(
        f"/api/analyses/{public_id}/recommendations/0/reject", json={"note": "changed my mind"}
    )

    assert again.status_code == 409


def test_deciding_on_a_recommendation_that_is_not_there_is_a_404(agent_env) -> None:
    http, _caller, _identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]

    response = http.post(f"/api/analyses/{public_id}/recommendations/99/approve", json={"note": ""})

    assert response.status_code == 404


def test_another_organization_cannot_see_or_decide(agent_env) -> None:
    """A run holds a supplier's risk profile and somebody's reasoning about it. Across
    tenants that is a breach, so a miss is a 404 rather than a 403 — a 403 confirms the
    id exists, which is how ids get enumerated."""

    http, caller, identities, _client, _maker = agent_env
    public_id = _start(http).json()["public_id"]
    caller["identity"] = identities["globex-admin"]

    assert http.get(f"/api/analyses/{public_id}").status_code == 404
    assert (
        http.post(
            f"/api/analyses/{public_id}/recommendations/0/approve", json={"note": "x"}
        ).status_code
        == 404
    )
    assert http.get("/api/analyses").json()["items"] == []


def test_the_list_is_this_organizations_analyses(agent_env) -> None:
    http, _caller, _identities, _client, _maker = agent_env
    _start(http)
    _start(http)

    body = http.get("/api/analyses").json()

    assert body["total"] == 2
    assert all(item["supplier_public_id"] == "acme-parts" for item in body["items"])


def test_a_decision_is_audited(agent_env) -> None:
    """The record that answers "who agreed to this". Naming the run and the ordinal
    matters as much as naming the actor — an audit line that says only "approved
    something" is not evidence of anything."""

    http, _caller, identities, _client, maker = agent_env
    public_id = _start(http).json()["public_id"]

    http.post(f"/api/analyses/{public_id}/recommendations/0/approve", json={"note": "Agreed."})

    async def decisions():
        async with maker() as session:
            rows = await session.execute(
                select(AuditLog).where(AuditLog.action == "agent.recommendation_approved")
            )
            return list(rows.scalars().all())

    entries = asyncio.run(decisions())
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_email == identities["acme-admin"].email
    assert entry.resource_id == public_id
    assert entry.detail["ordinal"] == 0
    assert entry.detail["note"] == "Agreed."


def test_running_an_analysis_is_audited(agent_env) -> None:
    http, _caller, _identities, _client, maker = agent_env

    public_id = _start(http).json()["public_id"]

    async def runs():
        async with maker() as session:
            rows = await session.execute(
                select(AuditLog).where(AuditLog.action == "agent.analysis_run")
            )
            return list(rows.scalars().all())

    entries = asyncio.run(runs())
    assert len(entries) == 1
    assert entries[0].resource_id == public_id
    assert entries[0].detail["supplier_public_id"] == "acme-parts"
