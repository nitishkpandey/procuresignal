"""The bounded loop.

Everything worth asserting here is about limits rather than intelligence: that the loop
stops, that it stops for a reason it records, that it never spends past the cap, and that
it cannot be talked into calling something the catalogue does not contain.

No test reaches the network. A fake client drives the loop and a stubbed transport checks
the request shape once.
"""

import json
from datetime import datetime

import httpx
import pytest
from procuresignal.agents.client import AgentTurn, OpenAIAgentClient, ToolCall
from procuresignal.agents.loop import MAX_STEPS, run_loop
from procuresignal.enrichment.budget import DAILY_TOKEN_BUDGET, consume
from procuresignal.models import AgentRun, AgentStep, Membership, Organization, Role, User
from procuresignal.observability import metrics as metrics_module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

TOOLS = [
    {
        "type": "function",
        "name": "get_supplier_impact",
        "description": "Impact score and drivers for a supplier",
        "parameters": {
            "type": "object",
            "properties": {"supplier_public_id": {"type": "string"}},
            "required": ["supplier_public_id"],
            "additionalProperties": False,
        },
    }
]


class FakeClient:
    """Replays a scripted list of turns and records what it was asked."""

    name = "fake-agent-model"

    def __init__(self, turns: list[AgentTurn], on_call=None):
        self.turns = list(turns)
        self.requests: list[list[dict]] = []
        self.on_call = on_call

    async def respond(self, *, instructions: str, input: list[dict], tools: list[dict]):
        self.requests.append(list(input))
        if self.on_call is not None:
            await self.on_call(len(self.requests))
        if not self.turns:
            return AgentTurn(text="done", tool_calls=[], prompt_tokens=1, completion_tokens=1)
        return self.turns.pop(0)


def _answer(text: str = "Here is the analysis.") -> AgentTurn:
    return AgentTurn(text=text, tool_calls=[], prompt_tokens=10, completion_tokens=5)


def _calls(*names: str) -> AgentTurn:
    return AgentTurn(
        text=None,
        tool_calls=[
            ToolCall(call_id=f"call-{index}", name=name, arguments={"supplier_public_id": "acme"})
            for index, name in enumerate(names)
        ],
        prompt_tokens=10,
        completion_tokens=5,
    )


async def _tenant(session: AsyncSession) -> tuple[int, int]:
    organization = Organization(public_id="org-acme", name="acme", slug="acme")
    session.add(organization)
    await session.flush()
    user = User(public_id="user-acme", email="buyer@acme.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return organization.id, user.id


async def _run(session: AsyncSession) -> AgentRun:
    organization_id, user_id = await _tenant(session)
    run = AgentRun(
        public_id="run-1",
        organization_id=organization_id,
        requested_by_user_id=user_id,
        supplier_public_id="acme",
        status="running",
        model="fake-agent-model",
        started_at=datetime.utcnow(),
    )
    session.add(run)
    await session.flush()
    return run


async def _dispatch(name: str, arguments: dict) -> dict:
    return {"band": "severe", "asked_for": arguments.get("supplier_public_id")}


async def _steps(session: AsyncSession, run: AgentRun) -> list[AgentStep]:
    result = await session.execute(
        select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.ordinal)
    )
    return list(result.scalars().all())


async def _loop(session, run, client, dispatch=_dispatch, **kwargs) -> str:
    return await run_loop(
        session,
        run=run,
        client=client,
        tools=TOOLS,
        dispatch=dispatch,
        instructions="Analyse the supplier.",
        opening="Analyse acme.",
        **kwargs,
    )


async def test_a_loop_that_calls_one_tool_then_answers(async_session: AsyncSession) -> None:
    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact"), _answer("Acme is severely exposed.")])

    text = await _loop(async_session, run, client)

    assert text == "Acme is severely exposed."
    assert run.status == "completed"
    assert [step.kind for step in await _steps(async_session, run)] == [
        "tool_call",
        "tool_result",
        "model_message",
    ]


async def test_an_answer_with_no_tools_is_a_complete_run(async_session: AsyncSession) -> None:
    run = await _run(async_session)

    text = await _loop(async_session, run, FakeClient([_answer()]))

    assert text == "Here is the analysis."
    assert run.status == "completed"
    assert run.step_count == 1


async def test_the_tool_result_reaches_the_next_request(async_session: AsyncSession) -> None:
    """The loop is only a loop if the result comes back. Feeding an empty result would
    still terminate and still look like a working analysis."""

    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact"), _answer()])

    await _loop(async_session, run, client)

    second_request = client.requests[1]
    outputs = [item for item in second_request if item.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["call_id"] == "call-0"
    assert "severe" in outputs[0]["output"]


async def test_every_turn_is_on_the_record_before_the_next_is_asked_for(
    async_session: AsyncSession,
) -> None:
    """A run that crashes mid-loop has to leave a readable partial transcript. If steps
    were flushed at the end, a crash would erase the evidence of what caused it."""

    seen: list[int] = []

    async def spy(request_number: int) -> None:
        rows = await async_session.execute(select(AgentStep))
        seen.append(len(list(rows.scalars().all())))

    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact"), _answer()], on_call=spy)

    await _loop(async_session, run, client)

    # Nothing before the first request; the call and its result before the second.
    assert seen == [0, 2]


async def test_the_step_ceiling_stops_a_loop_that_will_not_finish(
    async_session: AsyncSession,
) -> None:
    """A loop with no ceiling is an unbounded bill and an unbounded wait. Asking the
    model in the prompt to stop is a request, not a limit."""

    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact") for _ in range(MAX_STEPS + 5)])

    await _loop(async_session, run, client)

    assert run.status == "failed"
    assert run.failure_reason == "step_ceiling"
    assert len(client.requests) <= MAX_STEPS


async def test_a_truncated_run_is_not_presented_as_a_finished_one(
    async_session: AsyncSession,
) -> None:
    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact") for _ in range(MAX_STEPS + 5)])

    text = await _loop(async_session, run, client)

    assert text == ""
    assert run.finished_at is not None


async def test_an_exhausted_budget_refuses_before_the_first_call(
    async_session: AsyncSession,
) -> None:
    """The cap that exists to stop a runaway has to bind here too. Embedding and
    enrichment already respect it; an agent loop is the most expensive thing in the
    system per invocation."""

    run = await _run(async_session)
    await consume(async_session, tenant=None, tokens=DAILY_TOKEN_BUDGET, calls=1)
    client = FakeClient([_answer()])
    before = metrics_module.LLM_BUDGET_REFUSALS.labels(tenant="__global__")._value.get()

    await _loop(async_session, run, client)

    assert client.requests == [], "the model was called with no budget left"
    assert run.status == "failed"
    assert run.failure_reason == "budget_exhausted"
    assert metrics_module.LLM_BUDGET_REFUSALS.labels(tenant="__global__")._value.get() > before


async def test_spend_is_recorded_against_the_run(async_session: AsyncSession) -> None:
    run = await _run(async_session)

    await _loop(async_session, run, FakeClient([_calls("get_supplier_impact"), _answer()]))

    assert run.prompt_tokens == 20
    assert run.completion_tokens == 10


async def test_a_tool_the_catalogue_does_not_have_is_never_dispatched(
    async_session: AsyncSession,
) -> None:
    """The security boundary in miniature. A model that asks for `delete_watchlist` must
    not reach a dispatcher that might grow one later, and the attempt has to be on the
    record rather than silently corrected.
    """

    dispatched: list[str] = []

    async def recording_dispatch(name: str, arguments: dict) -> dict:
        dispatched.append(name)
        return {"ok": True}

    run = await _run(async_session)
    client = FakeClient([_calls("delete_watchlist"), _answer()])

    await _loop(async_session, run, client, dispatch=recording_dispatch)

    assert dispatched == [], "an unknown tool reached the dispatcher"
    steps = await _steps(async_session, run)
    assert steps[0].tool_name == "delete_watchlist"
    assert steps[0].kind == "tool_call"
    assert "unknown tool" in json.dumps(steps[1].payload_json).lower()


async def test_the_model_is_told_its_tool_call_failed(async_session: AsyncSession) -> None:
    """Refusal is returned as a tool result rather than raised, so the model can
    recover within the same run instead of the whole analysis being lost."""

    run = await _run(async_session)
    client = FakeClient([_calls("delete_watchlist"), _answer("Understood, using what I have.")])

    text = await _loop(async_session, run, client)

    assert text == "Understood, using what I have."
    assert run.status == "completed"


async def test_a_tool_that_raises_does_not_lose_the_run(async_session: AsyncSession) -> None:
    async def broken(name: str, arguments: dict) -> dict:
        raise RuntimeError("the database is on fire")

    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact"), _answer("Partial analysis.")])

    text = await _loop(async_session, run, client, dispatch=broken)

    assert text == "Partial analysis."
    steps = await _steps(async_session, run)
    assert "error" in json.dumps(steps[1].payload_json).lower()
    # The message is not fed back verbatim: an internal exception string is not
    # something to hand to a model that will quote it into a recommendation.
    assert "on fire" not in json.dumps(steps[1].payload_json)


async def test_several_tool_calls_in_one_turn_are_all_run(async_session: AsyncSession) -> None:
    """The Responses API sets `parallel_tool_calls` by default, so a turn can carry
    more than one. Handling only the first would silently drop evidence."""

    run = await _run(async_session)
    client = FakeClient([_calls("get_supplier_impact", "get_supplier_impact"), _answer()])

    await _loop(async_session, run, client)

    steps = await _steps(async_session, run)
    assert [step.kind for step in steps[:4]] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]


async def test_the_client_refuses_to_start_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)

    with pytest.raises(ValueError):
        OpenAIAgentClient()


async def test_the_request_openai_receives_carries_the_tools_and_the_input() -> None:
    """The one test that touches the real client, against a stubbed transport.

    The shape asserted here was verified against the live API before it was written:
    tool calls come back as `output` items of type `function_call` carrying a `call_id`,
    and results go back as input items of type `function_call_output` with the same id.
    """

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_abc",
                        "name": "get_supplier_impact",
                        "arguments": '{"supplier_public_id": "acme"}',
                    }
                ],
                "usage": {"input_tokens": 64, "output_tokens": 25},
            },
        )

    client = OpenAIAgentClient(
        api_key="test-key", model="gpt-5.4-mini", transport=httpx.MockTransport(handler)
    )
    turn = await client.respond(
        instructions="Analyse the supplier.",
        input=[{"role": "user", "content": "Analyse acme."}],
        tools=TOOLS,
    )

    assert seen["url"] == "https://api.openai.com/v1/responses"
    payload = seen["payload"]
    assert payload["model"] == "gpt-5.4-mini"
    assert payload["tools"] == TOOLS
    assert payload["instructions"] == "Analyse the supplier."
    assert turn.tool_calls == [
        ToolCall(
            call_id="call_abc", name="get_supplier_impact", arguments={"supplier_public_id": "acme"}
        )
    ]
    assert (turn.prompt_tokens, turn.completion_tokens) == (64, 25)


async def test_text_output_is_read_from_a_message_item() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Acme is exposed."}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )

    client = OpenAIAgentClient(api_key="test-key", transport=httpx.MockTransport(handler))
    turn = await client.respond(instructions="x", input=[], tools=[])

    assert turn.text == "Acme is exposed."
    assert turn.tool_calls == []


async def test_arguments_that_are_not_json_do_not_crash_the_client() -> None:
    """A model returning malformed arguments is a bad turn, not an exception. The loop
    turns it into a tool result the model can correct."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_bad",
                        "name": "get_supplier_impact",
                        "arguments": "{not json",
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = OpenAIAgentClient(api_key="test-key", transport=httpx.MockTransport(handler))
    turn = await client.respond(instructions="x", input=[], tools=[])

    assert turn.tool_calls[0].arguments == {}
