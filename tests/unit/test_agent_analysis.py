"""Turning what the model said into something a buyer can act on.

The load-bearing test in this file is the one about citations. A fabricated reference is
the characteristic failure of this class of system: the recommendation reads perfectly,
the evidence key looks exactly like a real one, and nothing downstream notices until an
auditor asks to see the article. Every key is checked against what the tools actually
returned during the same run, and the ones that do not match are dropped.
"""

import json
from datetime import datetime

import pytest
from procuresignal.agents.analysis import (
    UNPARSEABLE,
    analyse_supplier,
    event_keys_in,
    parse_analysis,
)
from procuresignal.agents.client import AgentTurn, ToolCall
from procuresignal.models import (
    AgentRecommendation,
    AgentRun,
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


class ScriptedClient:
    name = "scripted-model"

    def __init__(self, turns):
        self.turns = list(turns)

    async def respond(self, *, instructions, input, tools):
        return self.turns.pop(0)


def _answer(payload) -> AgentTurn:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return AgentTurn(text=text, tool_calls=[], prompt_tokens=10, completion_tokens=5)


def _tool_turn(name="list_risk_events") -> AgentTurn:
    return AgentTurn(
        text=None,
        tool_calls=[
            ToolCall(call_id="c0", name=name, arguments={"supplier_public_id": "acme-parts"})
        ],
        prompt_tokens=10,
        completion_tokens=5,
    )


async def _fixture(session: AsyncSession) -> tuple[int, int]:
    organization = Organization(public_id="org-acme", name="acme", slug="acme")
    session.add(organization)
    await session.flush()
    user = User(public_id="user-acme", email="b@acme.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
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
            event_key="acme-strike-2026-08",
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
    await session.commit()
    return organization.id, user.id


def test_event_keys_are_found_wherever_a_tool_put_them() -> None:
    """Tools nest their keys differently — impact returns drivers, list_risk_events
    returns events — so the collector walks the structure rather than knowing shapes."""

    payload = {
        "drivers": [{"event_key": "a"}, {"event_key": "b"}],
        "nested": {"events": [{"event_key": "c"}]},
    }

    assert event_keys_in(payload) == {"a", "b", "c"}


def test_a_reply_that_is_not_json_is_not_an_analysis() -> None:
    assert parse_analysis("I had a think and here are my thoughts.") is None


def test_a_json_reply_wrapped_in_a_code_fence_is_still_json() -> None:
    """Models fence JSON constantly. Failing the run over punctuation would throw away
    a perfectly good analysis and bill for it twice."""

    fenced = '```json\n{"findings": ["a"], "recommendations": []}\n```'

    parsed = parse_analysis(fenced)

    assert parsed is not None
    assert parsed["findings"] == ["a"]


def test_a_json_array_is_not_the_contract() -> None:
    assert parse_analysis('["just", "a", "list"]') is None


async def test_a_recommendation_keeps_the_citations_a_tool_returned(
    async_session: AsyncSession,
) -> None:
    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient(
        [
            _tool_turn(),
            _answer(
                {
                    "findings": ["An open strike at the main plant."],
                    "recommendations": [
                        {
                            "title": "Qualify a second source",
                            "rationale": "The strike is unresolved.",
                            "evidence_event_keys": ["acme-strike-2026-08"],
                        }
                    ],
                }
            ),
        ]
    )

    run = await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    stored = (await async_session.execute(select(AgentRecommendation))).scalars().all()
    assert run.status == "completed"
    assert len(stored) == 1
    assert stored[0].evidence_event_keys == ["acme-strike-2026-08"]
    assert stored[0].status == "proposed"


async def test_a_citation_no_tool_returned_is_dropped(async_session: AsyncSession) -> None:
    """The load-bearing test. A key the model invented looks exactly like a real one,
    and the recommendation reads perfectly either way."""

    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient(
        [
            _tool_turn(),
            _answer(
                {
                    "findings": [],
                    "recommendations": [
                        {
                            "title": "Hold new orders",
                            "rationale": "Cited an event that does not exist.",
                            "evidence_event_keys": [
                                "acme-strike-2026-08",
                                "acme-bankruptcy-2026-09",
                            ],
                        }
                    ],
                }
            ),
        ]
    )

    await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    stored = (await async_session.execute(select(AgentRecommendation))).scalar_one()
    assert stored.evidence_event_keys == ["acme-strike-2026-08"]


async def test_what_was_dropped_is_recorded_rather_than_quietly_discarded(
    async_session: AsyncSession,
) -> None:
    """A model that invents citations is a fact about the run worth keeping. Silently
    cleaning up would hide exactly the signal that says this output needs review."""

    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient(
        [
            _tool_turn(),
            _answer(
                {
                    "findings": [],
                    "recommendations": [
                        {
                            "title": "Hold new orders",
                            "rationale": "x",
                            "evidence_event_keys": ["invented-key"],
                        }
                    ],
                }
            ),
        ]
    )

    run = await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    checks = (
        (
            await async_session.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run.id)
                .where(AgentStep.kind == "evidence_check")
            )
        )
        .scalars()
        .all()
    )
    assert len(checks) == 1
    assert checks[0].payload_json["dropped"] == ["invented-key"]


async def test_a_recommendation_left_with_no_evidence_is_not_stored(
    async_session: AsyncSession,
) -> None:
    """If every citation was invented, what remains is an assertion with nothing behind
    it. Storing it would put an unsupported claim in front of a buyer with the same
    weight as a supported one."""

    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient(
        [
            _tool_turn(),
            _answer(
                {
                    "findings": [],
                    "recommendations": [
                        {"title": "Trust me", "rationale": "x", "evidence_event_keys": ["nope"]}
                    ],
                }
            ),
        ]
    )

    await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    assert (await async_session.execute(select(AgentRecommendation))).scalars().all() == []


async def test_unparseable_output_fails_the_run(async_session: AsyncSession) -> None:
    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient([_answer("Sorry, I could not work that out.")])

    run = await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    assert run.status == "failed"
    assert run.failure_reason == UNPARSEABLE
    assert (await async_session.execute(select(AgentRecommendation))).scalars().all() == []


async def test_an_unknown_supplier_is_refused_before_anything_is_spent(
    async_session: AsyncSession,
) -> None:
    """No run, no row, no tokens. Creating a failed run for a typo would fill the table
    with noise and bill for it."""

    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient([])

    with pytest.raises(ValueError):
        await analyse_supplier(
            async_session,
            organization_id=organization_id,
            user_id=user_id,
            supplier_public_id="no-such-supplier",
            client=client,
        )

    assert (await async_session.execute(select(AgentRun))).scalars().all() == []


async def test_the_run_records_which_model_produced_it(async_session: AsyncSession) -> None:
    """Two models are two behaviours. A transcript that does not say which one ran
    cannot be compared with another."""

    organization_id, user_id = await _fixture(async_session)
    client = ScriptedClient([_answer({"findings": [], "recommendations": []})])

    run = await analyse_supplier(
        async_session,
        organization_id=organization_id,
        user_id=user_id,
        supplier_public_id="acme-parts",
        client=client,
    )

    assert run.model == "scripted-model"
    assert run.public_id
