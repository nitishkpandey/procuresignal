"""The bounded loop.

Three limits, all enforced in code rather than requested in the prompt, because a prompt
is a request and this is an unbounded bill otherwise:

- **A step ceiling.** A model that keeps calling tools stops after `MAX_STEPS`, and the
  run is marked failed. A truncated analysis presented as a finished one is worse than
  an error.
- **The daily budget cap.** Checked before every turn and charged after it, the same
  guard enrichment and embedding already use. An agent loop is the most expensive thing
  in this system per invocation.
- **The tool catalogue.** A name the catalogue does not contain is never dispatched. The
  refusal is returned to the model as a tool result so it can recover, and the attempt is
  recorded so a reviewer can see it was made.

Every turn is written to `agent_steps` before the next one is requested, so a run that
crashes mid-loop leaves a readable partial transcript. That is the difference between
diagnosing a failure and guessing at one.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.agents.client import AgentClient, AgentTurn, ToolCall
from procuresignal.enrichment.budget import (
    GLOBAL_BUCKET,
    BudgetExceededError,
    consume,
    consume_overage,
    within_budget,
)
from procuresignal.models import AgentRun, AgentStep
from procuresignal.observability.metrics import record_budget_refusal

logger = logging.getLogger(__name__)

# Eight turns is comfortably more than the four tools need and far short of a loop that
# has stopped making progress. Raising it is a cost decision, not a correctness one.
MAX_STEPS = 8

# Charged before each turn, since the bill arrives whether or not the reply is useful.
# Deliberately generous: a cap that under-counts permits more spend than it advertises.
ESTIMATED_TOKENS_PER_TURN = 4000

# The dispatcher is a closure the caller builds with its session and organization already
# bound. The loop never sees an organization id, so a prompt-injected argument has
# nothing to reach.
ToolDispatch = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def _record(
    session: AsyncSession,
    run: AgentRun,
    ordinal: int,
    kind: str,
    payload: dict[str, Any],
    tool_name: str | None = None,
) -> None:
    session.add(
        AgentStep(
            run_id=run.id,
            ordinal=ordinal,
            kind=kind,
            tool_name=tool_name,
            payload_json=payload,
        )
    )
    run.step_count = ordinal + 1
    await session.commit()


async def _finish(
    session: AsyncSession, run: AgentRun, status: str, reason: str | None = None
) -> None:
    run.status = status
    run.failure_reason = reason
    run.finished_at = datetime.utcnow()
    await session.commit()


async def _charge(session: AsyncSession, turn: AgentTurn, run: AgentRun) -> None:
    spent = turn.prompt_tokens + turn.completion_tokens
    run.prompt_tokens += turn.prompt_tokens
    run.completion_tokens += turn.completion_tokens
    if not spent:
        return
    try:
        await consume(session, tenant=None, tokens=spent)
    except BudgetExceededError:
        # The turn already happened as the cap ran out. Record what it cost rather than
        # lose the accounting, and the next turn's check will refuse.
        await consume_overage(session, tenant=None, tokens=spent)


async def _run_tool(
    dispatch: ToolDispatch, call: ToolCall, known: set[str]
) -> tuple[dict[str, Any], str]:
    """Execute one tool call. Returns what to store and what to tell the model."""

    if call.name not in known:
        # Never dispatched. The dispatcher might grow a write tool one day; this is the
        # line that means a model asking for one still cannot reach it.
        logger.warning("agent asked for unknown tool %r", call.name)
        message = f"unknown tool {call.name!r}; use only the tools provided"
        return {"error": message}, message

    try:
        result = await dispatch(call.name, call.arguments)
    except Exception:
        # The internal message is logged, not returned: an exception string is not
        # something to hand to a model that will quote it into a recommendation.
        logger.exception("agent tool %r failed", call.name)
        message = f"tool {call.name!r} failed"
        return {"error": message}, message

    return result, json.dumps(result, default=str)


async def run_loop(
    session: AsyncSession,
    *,
    run: AgentRun,
    client: AgentClient,
    tools: Sequence[dict[str, Any]],
    dispatch: ToolDispatch,
    instructions: str,
    opening: str,
    max_steps: int = MAX_STEPS,
) -> str:
    """Drive the model until it answers, gives up, or hits a limit.

    Returns the model's final text, or an empty string if the run ended without one.
    """

    known = {str(tool.get("name")) for tool in tools}
    conversation: list[dict[str, Any]] = [{"role": "user", "content": opening}]
    ordinal = 0

    for _ in range(max_steps):
        if not await within_budget(session, tenant=None, tokens=ESTIMATED_TOKENS_PER_TURN):
            record_budget_refusal(GLOBAL_BUCKET)
            await _finish(session, run, "failed", "budget_exhausted")
            return ""

        turn = await client.respond(
            instructions=instructions, input=conversation, tools=list(tools)
        )
        await _charge(session, turn, run)

        if not turn.tool_calls:
            await _record(session, run, ordinal, "model_message", {"text": turn.text or ""})
            await _finish(session, run, "completed")
            return turn.text or ""

        for call in turn.tool_calls:
            conversation.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                }
            )
            await _record(
                session,
                run,
                ordinal,
                "tool_call",
                {"call_id": call.call_id, "arguments": call.arguments},
                tool_name=call.name,
            )
            ordinal += 1

            stored, reply = await _run_tool(dispatch, call, known)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": reply,
                }
            )
            await _record(session, run, ordinal, "tool_result", stored, tool_name=call.name)
            ordinal += 1

    # Out of steps with no answer. Recorded as a failure rather than returned as one,
    # because a partial analysis that looks finished is the more dangerous outcome.
    await _finish(session, run, "failed", "step_ceiling")
    return ""
