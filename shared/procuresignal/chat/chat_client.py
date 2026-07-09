"""OpenAI-backed chat client for the conversational analyst."""

from collections.abc import AsyncIterator

from procuresignal.enrichment.openai_client import OpenAILLMClient


class ChatLLMClient:
    """Chat client backed by OpenAI Responses API."""

    MODEL = OpenAILLMClient.MODEL
    MAX_TOKENS = 1024

    def __init__(self, api_key: str | None = None):
        self.client = OpenAILLMClient(
            api_key=api_key,
            max_tokens=self.MAX_TOKENS,
        )
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

        prompt = _format_conversation(history, user_message)
        self.last_tokens_used = 0
        text = await self.client.call(system_prompt=system_prompt, user_message=prompt)
        self.last_tokens_used = getattr(self.client, "last_tokens_used", 0)
        if text:
            yield text


def _format_conversation(history: list[dict], user_message: str) -> str:
    """Flatten recent chat context for the Responses API input."""
    lines: list[str] = []
    for message in history:
        role = str(message.get("role", "user")).strip().lower() or "user"
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    lines.append(f"user: {user_message}")
    return "\n".join(lines)
