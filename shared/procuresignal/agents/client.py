"""The Responses API, reduced to what a tool loop needs.

Two rules shape the parsing. Nothing raises on a malformed turn — a model returning
arguments that are not JSON is a bad turn the loop can recover from, not an exception
that loses the whole analysis. And nothing is inferred: tool calls are read from `output`
items of type `function_call`, which is the shape verified against `gpt-5.4-mini` before
this was written rather than the shape remembered from documentation.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from procuresignal.config.secrets import get_secret
from procuresignal.enrichment.openai_client import extract_output_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTurn:
    """One reply from the model: something to say, something to call, or both."""

    text: str | None
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int


class AgentClient(Protocol):
    """What the loop needs. Implemented for real below and faked in tests."""

    name: str

    async def respond(
        self, *, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AgentTurn: ...


def _retryable(error: BaseException) -> bool:
    # Same policy as the embedding provider: wait for what can succeed later, and fail
    # immediately on what cannot. A 401 retried three times is three failures and a delay.
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or error.response.status_code >= 500
    return False


def _arguments(raw: Any) -> dict[str, Any]:
    """Parse a tool call's arguments, treating anything unusable as empty.

    The loop hands the resulting call to a dispatcher that validates its arguments and
    returns an error the model can read. Raising here would turn a recoverable bad turn
    into a lost run.
    """

    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("agent returned tool arguments that are not JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OpenAIAgentClient:
    """`gpt-5.4-mini` by default: capable enough for multi-step tool use, and an order
    of magnitude cheaper than the full model for a task whose answer a human reads and
    checks anyway."""

    BASE_URL = "https://api.openai.com/v1/responses"
    MODEL = "gpt-5.4-mini"
    MAX_OUTPUT_TOKENS = 2000

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # Through the resolver so OPENAI_API_KEY_FILE and /run/secrets work.
        self.api_key = api_key or get_secret("OPENAI_API_KEY", default="")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.name: str = model or os.getenv("OPENAI_AGENT_MODEL") or self.MODEL
        self.timeout = timeout
        # Only ever set by tests, which assert request shape rather than send one.
        self._transport = transport

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_retryable),
    )
    async def respond(
        self, *, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AgentTurn:
        payload = {
            "model": self.name,
            "instructions": instructions,
            "input": input,
            "tools": tools,
            "max_output_tokens": self.MAX_OUTPUT_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        calls = [
            ToolCall(
                call_id=str(item.get("call_id") or ""),
                name=str(item.get("name") or ""),
                arguments=_arguments(item.get("arguments")),
            )
            for item in data.get("output") or []
            if isinstance(item, dict) and item.get("type") == "function_call"
        ]

        text = extract_output_text(data)
        return AgentTurn(
            text=text or None,
            tool_calls=calls,
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
        )


def agent_client() -> AgentClient | None:
    """The configured client, or None when there is no key.

    None is a supported state, not an error: the endpoint answers 503 with a reason.
    An analysis produced without a model would be a plausible-looking document with
    nothing behind it, which is the worst possible output for this feature.
    """

    if not get_secret("OPENAI_API_KEY", default=""):
        return None
    return OpenAIAgentClient()
