"""Tests for the chat client (OpenAI stubbed)."""

import asyncio

import pytest
from procuresignal.chat.chat_client import ChatLLMClient


class _FakeOpenAIClient:
    def __init__(self, captured):
        self._captured = captured
        self.last_tokens_used = 42

    async def call(self, system_prompt: str, user_message: str) -> str:
        self._captured["system_prompt"] = system_prompt
        self._captured["user_message"] = user_message
        return "Hello, world"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        ChatLLMClient()


def test_stream_chat_calls_openai_with_context(monkeypatch):
    captured: dict = {}
    client = ChatLLMClient(api_key="test-key")
    client.client = _FakeOpenAIClient(captured)

    async def run():
        out = []
        async for delta in client.stream_chat(
            system_prompt="SYS",
            history=[{"role": "user", "content": "earlier"}],
            user_message="now",
        ):
            out.append(delta)
        return out

    out = asyncio.run(run())
    assert out == ["Hello, world"]
    assert client.last_tokens_used == 42

    assert captured["system_prompt"] == "SYS"
    assert "user: earlier" in captured["user_message"]
    assert captured["user_message"].endswith("user: now")
