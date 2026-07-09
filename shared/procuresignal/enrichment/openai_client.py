"""OpenAI Responses API client for enrichment and chat."""

import os
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class OpenAILLMClient:
    """Small async client for OpenAI text responses."""

    BASE_URL = "https://api.openai.com/v1/responses"
    MODEL = "gpt-5.5"
    MAX_TOKENS = 500

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.model = model or os.getenv("OPENAI_MODEL", self.MODEL)
        self.max_tokens = max_tokens or self.MAX_TOKENS
        self.timeout = timeout
        self.total_tokens_used = 0
        self.total_api_calls = 0
        self.last_tokens_used = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)
        ),
    )
    async def call(self, system_prompt: str, user_message: str) -> str:
        """Call the Responses API and return plain text output."""
        payload = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_message,
            "max_output_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        self.last_tokens_used = _total_tokens(data.get("usage"))
        self.total_tokens_used += self.last_tokens_used
        self.total_api_calls += 1
        return _extract_output_text(data)

    def get_usage_stats(self) -> dict:
        """Get token usage statistics."""
        return {
            "total_tokens": self.total_tokens_used,
            "total_calls": self.total_api_calls,
            "avg_tokens_per_call": (
                self.total_tokens_used / self.total_api_calls if self.total_api_calls > 0 else 0
            ),
        }


def _extract_output_text(data: dict[str, Any]) -> str:
    """Extract text from common Responses API response shapes."""
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _total_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    if isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return input_tokens + output_tokens
    return 0
