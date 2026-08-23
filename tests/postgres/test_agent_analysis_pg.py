"""The analysis over a real database.

The unit tests script the model and stub nothing else; here the tools run against the
migrated schema, so the citations a recommendation survives with are keys that genuinely
exist in `risk_events`. That is the claim the whole evidence contract rests on, and it
cannot be made on a schema built from the ORM.

The model is still scripted. What a real model would say is not a property this suite can
assert without spending money to learn something non-deterministic.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.agents.analysis import analyse_supplier
from procuresignal.agents.client import AgentTurn, ToolCall
from procuresignal.agents.tools import dispatch
from procuresignal.models import (
    AgentRecommendation,
    AgentStep,
    Membership,
    Organization,
    RiskEvent,
    Role,
    Supplier,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

REAL_KEY = "acme-strike-2026-08"
INVENTED_KEY = "acme-bankruptcy-2026-09"


class ScriptedClient:
    name = "scripted-model"

    def __init__(self, turns):
        self.turns = list(turns)
        self.tools_offered: list[str] = []

    async def respond(self, *, instructions, input, tools):
        self.tools_offered = [tool["name"] for tool in tools]
        return self.turns.pop(0)


def _json_answer(text: str) -> AgentTurn:
    return AgentTurn(text=text, tool_calls=[], prompt_tokens=20, completion_tokens=10)


def _call(name: str, arguments: dict) -> AgentTurn:
    return AgentTurn(
        text=None,
        tool_calls=[ToolCall(call_id="c0", name=name, arguments=arguments)],
        prompt_tokens=20,
        completion_tokens=10,
    )


async def _fixture(session: AsyncSession) -> tuple[int, int]:
    organization = Organization(public_id="org-acme", name="acme", slug="acme")
    session.add(organization)
    await session.flush()
    user = User(public_id="user-acme", email="b@acme.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    session.add_all(
        [
            Supplier(
                public_id="acme-parts",
                canonical_name="Acme Parts GmbH",
                normalized_name="acme parts",
                country="DE",
                is_active=True,
            ),
            Supplier(
                public_id="rival-parts",
                canonical_name="Rival Components GmbH",
                normalized_name="rival components",
                country="DE",
                is_active=True,
            ),
        ]
    )
    session.add(
        RiskEvent(
            event_key=REAL_KEY,
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
            published_at=datetime.utcnow() - timedelta(days=1),
            status="new",
        )
    )
    await session.commit()
    return organization.id, user.id


async def test_only_citations_that_exist_survive_a_real_run(pg_session: AsyncSession) -> None:
    """The evidence contract, end to end against the shipped schema.

    The model cites one key it was shown and one it made up. Both look identical; only
    one of them is in `risk_events`.
    """

    organization_id, user_id = await _fixture(pg_session)
    client = ScriptedClient(
        [
            _call("list_risk_events", {"supplier_public_id": "acme-parts"}),
            _json_answer(
                '{"findings": ["An unresolved strike."], "recommendations": ['
                '{"title": "Qualify a second source", "rationale": "The strike is open.",'
                f' "evidence_event_keys": ["{REAL_KEY}", "{INVENTED_KEY}"]}}]}}'
            ),
        ]
    )

    run = await analyse_supplier(
        pg_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    stored = (await pg_session.execute(select(AgentRecommendation))).scalar_one()
    assert run.status == "completed"
    assert stored.evidence_event_keys == [REAL_KEY]

    # And the surviving key really is a row, not merely a string a tool echoed.
    exists = await pg_session.scalar(
        select(RiskEvent.event_key).where(RiskEvent.event_key == stored.evidence_event_keys[0])
    )
    assert exists == REAL_KEY


async def test_the_invention_is_visible_in_the_transcript(pg_session: AsyncSession) -> None:
    organization_id, user_id = await _fixture(pg_session)
    client = ScriptedClient(
        [
            _call("list_risk_events", {"supplier_public_id": "acme-parts"}),
            _json_answer(
                '{"findings": [], "recommendations": [{"title": "Hold orders",'
                f' "rationale": "x", "evidence_event_keys": ["{REAL_KEY}", "{INVENTED_KEY}"]}}]}}'
            ),
        ]
    )

    run = await analyse_supplier(
        pg_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    check = (
        await pg_session.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run.id)
            .where(AgentStep.kind == "evidence_check")
        )
    ).scalar_one()
    assert check.payload_json["dropped"] == [INVENTED_KEY]
    assert REAL_KEY in check.payload_json["verified"]


async def test_the_agent_is_offered_only_read_only_tools(pg_session: AsyncSession) -> None:
    """Whatever else changes, the catalogue handed to the model stays these four."""

    organization_id, user_id = await _fixture(pg_session)
    client = ScriptedClient([_json_answer('{"findings": [], "recommendations": []}')])

    await analyse_supplier(
        pg_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    assert sorted(client.tools_offered) == [
        "find_alternate_suppliers",
        "get_supplier_impact",
        "list_risk_events",
        "search_articles",
    ]


async def test_the_impact_tool_agrees_with_the_score_the_ui_shows(
    pg_session: AsyncSession,
) -> None:
    """The agent and the watchlist badge must not disagree about the same supplier.
    Two numbers for one question is the fastest way to lose a buyer's trust in both."""

    organization_id, _user_id = await _fixture(pg_session)

    from procuresignal.scoring.impact import supplier_impact

    direct = await supplier_impact(pg_session, supplier_public_id="acme-parts")
    through_tool = await dispatch(
        pg_session,
        name="get_supplier_impact",
        arguments={"supplier_public_id": "acme-parts"},
        organization_id=organization_id,
    )

    assert direct is not None
    assert through_tool["band"] == direct.score.band
    assert through_tool["value"] == pytest.approx(round(direct.score.value, 4))


async def test_the_search_tool_runs_against_real_retrieval(pg_session: AsyncSession) -> None:
    """`search_articles` is the one tool whose implementation is dialect-specific all
    the way down — tsvector, GIN, and pgvector. On SQLite it exercises a different code
    path entirely."""

    organization_id, _user_id = await _fixture(pg_session)

    result = await dispatch(
        pg_session,
        name="search_articles",
        arguments={"query": "port strike"},
        organization_id=organization_id,
    )

    assert result["mode"] in {"hybrid", "lexical", "degraded"}
    assert isinstance(result["articles"], list)
