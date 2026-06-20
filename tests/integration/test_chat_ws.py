"""Integration test for the chat WebSocket (Groq stubbed)."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import api.routers.chat as chat_router
from api.main import app


class _StubChatClient:
    last_tokens_used = 7

    async def stream_chat(self, system_prompt, history, user_message):
        for delta in ["The ", "tariff ", "raises costs."]:
            yield delta


@pytest.fixture()
def ws_client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    session_maker = asyncio.run(prepare())
    original = database_module.db_config
    db_config = database_module.DatabaseConfig("sqlite+aiosqlite://")
    db_config.engine = engine
    db_config.session_maker = session_maker
    database_module.db_config = db_config

    monkeypatch.setattr(chat_router, "_build_chat_client", lambda: _StubChatClient())

    with TestClient(app) as client:
        yield client
    database_module.db_config = original
    asyncio.run(engine.dispose())


def test_ws_streams_and_persists(ws_client: TestClient):
    with ws_client.websocket_connect("/api/ws/chat/u1/conv-1") as ws:
        ws.send_json({"message": "What does the tariff mean?"})

        assert ws.receive_json() == {"type": "start", "content": "Processing your message..."}
        streamed = []
        frame = ws.receive_json()
        while frame["type"] == "stream":
            streamed.append(frame["content"])
            frame = ws.receive_json()
        assert "".join(streamed) == "The tariff raises costs."
        assert frame["type"] == "end"

    # History persisted: 1 user + 1 assistant message
    resp = ws_client.get("/api/conversations/conv-1/messages")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total_count"] == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"] == "The tariff raises costs."
    assert payload["messages"][1]["tokens_used"] == 7


def test_ws_missing_message_field_errors_but_stays_open(ws_client: TestClient):
    with ws_client.websocket_connect("/api/ws/chat/u1/conv-2") as ws:
        ws.send_json({"not_message": "oops"})
        err = ws.receive_json()
        assert err["type"] == "error"
        # socket still usable
        ws.send_json({"message": "hello"})
        assert ws.receive_json()["type"] == "start"
