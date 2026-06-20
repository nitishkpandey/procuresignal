"""Streaming Groq chat client for the conversational analyst."""

import os
from collections.abc import AsyncIterator

from groq import AsyncGroq


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
        stream = await self.client.chat.completions.create(
            model=self.MODEL,
            messages=messages,
            max_tokens=self.MAX_TOKENS,
            temperature=0.4,
            stream=True,
        )
        async for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0].delta, "content", None)
                if delta:
                    yield delta
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self.last_tokens_used = getattr(usage, "total_tokens", 0) or 0
