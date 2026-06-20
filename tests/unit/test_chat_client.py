"""Tests for the streaming chat client (Groq stubbed)."""

import asyncio

import pytest
from procuresignal.chat.chat_client import ChatLLMClient


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = None


class _FakeStream:
    def __init__(self, contents):
        self._contents = contents

    def __aiter__(self):
        async def gen():
            for c in self._contents:
                yield _FakeChunk(c)

        return gen()


class _FakeCompletions:
    def __init__(self, captured):
        self._captured = captured

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeStream(["Hello", ", ", "world"])


class _FakeChat:
    def __init__(self, captured):
        self.completions = _FakeCompletions(captured)


class _FakeAsyncGroq:
    def __init__(self, captured):
        self.chat = _FakeChat(captured)


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError):
        ChatLLMClient()


def test_stream_chat_yields_deltas_and_assembles_messages(monkeypatch):
    captured: dict = {}
    client = ChatLLMClient(api_key="test-key")
    client.client = _FakeAsyncGroq(captured)

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
    assert out == ["Hello", ", ", "world"]

    messages = captured["messages"]
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[1] == {"role": "user", "content": "earlier"}
    assert messages[-1] == {"role": "user", "content": "now"}
    assert captured["stream"] is True
