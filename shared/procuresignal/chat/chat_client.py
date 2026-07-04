"""Streaming Groq chat client for the conversational analyst."""

import asyncio
import os
from collections.abc import AsyncIterator

from groq import AsyncGroq, RateLimitError


class ChatLLMClient:
    """Streaming chat client backed by Groq (Llama 3.1). Separate from enrichment."""

    MODEL = "llama-3.1-8b-instant"
    MAX_TOKENS = 1024

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set")
        self.client = AsyncGroq(api_key=self.api_key)
        self.last_tokens_used = 0

    async def stream_chat(
        self,
        system_prompt: str,
        history: list[dict],
        user_message: str,
    ) -> AsyncIterator[str]:
        """Stream the assistant's reply as text deltas.

        Args:
            system_prompt: Context-aware system instructions.
            history: Prior messages as ``{"role": ..., "content": ...}`` dicts.
            user_message: The new user message.
        """

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
        messages.append({"role": "user", "content": user_message})

        self.last_tokens_used = 0
        stream = await self._open_stream(messages)
        async for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0].delta, "content", None)
                if delta:
                    yield delta
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self.last_tokens_used = getattr(usage, "total_tokens", 0) or 0

    async def _open_stream(self, messages: list[dict]):
        """Open the streaming completion, riding out Groq's low free-tier rate limit.

        The free tier caps tokens-per-minute, so bursts of chat return 429; retry a
        few times honoring the ``retry-after`` hint before giving up with a clean error.
        """
        attempts = 4
        for attempt in range(attempts):
            try:
                return await self.client.chat.completions.create(
                    model=self.MODEL,
                    messages=messages,
                    max_tokens=self.MAX_TOKENS,
                    temperature=0.4,
                    stream=True,
                )
            except RateLimitError as exc:
                if attempt == attempts - 1:
                    raise RuntimeError(
                        "The assistant is rate-limited right now. Please try again in a few seconds."
                    ) from exc
                await asyncio.sleep(_retry_after(exc, default=2 * (attempt + 1)))


def _retry_after(exc: RateLimitError, default: float) -> float:
    """Seconds to wait from a 429's Retry-After header, capped, else ``default``."""
    try:
        value = float(exc.response.headers.get("retry-after", ""))
        return min(value + 0.5, 15.0)
    except (AttributeError, TypeError, ValueError):
        return default
