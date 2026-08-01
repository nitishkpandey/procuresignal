"""Integration test for the chat WebSocket (LLM stubbed)."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

import api.routers.chat as chat_router
from api.dependencies import get_current_user, get_current_ws_user
from api.main import app
from tests.conftest import fixed_identity


class _StubChatClient:
    last_tokens_used = 7

    async def stream_chat(self, system_prompt, history, user_message):
        for delta in ["The ", "tariff ", "raises costs."]:
            yield delta


@pytest.fixture()
def ws_client(monkeypatch):
    # The app lifespan calls init_db() when DATABASE_URL is set, overwriting the
    # in-memory SQLite db_config this fixture injects. CI sets DATABASE_URL (to an
    # unmigrated Postgres), so clear it for the duration of the test.
    monkeypatch.delenv("DATABASE_URL", raising=False)
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

    app.dependency_overrides[get_current_user] = lambda: fixed_identity("u1")
    app.dependency_overrides[get_current_ws_user] = lambda: fixed_identity("u1")
    with TestClient(app) as client:
        yield client
    database_module.db_config = original
    asyncio.run(engine.dispose())


def test_ws_streams_and_persists(ws_client: TestClient):
    with ws_client.websocket_connect("/api/ws/chat/conv-1") as ws:
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
    with ws_client.websocket_connect("/api/ws/chat/conv-2") as ws:
        ws.send_json({"not_message": "oops"})
        err = ws.receive_json()
        assert err["type"] == "error"
        # socket still usable
        ws.send_json({"message": "hello"})
        assert ws.receive_json()["type"] == "start"


# --- socket authentication ------------------------------------------------------

BEARER = "bearer"
PASSWORD = "a-sufficiently-long-password"
WS_UNAUTHENTICATED = 4401


def _self_authenticating(monkeypatch) -> None:
    """Drop the identity overrides so the socket authenticates for itself."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-that-is-long-enough-32")
    app.dependency_overrides.pop(get_current_ws_user, None)
    app.dependency_overrides.pop(get_current_user, None)


def _register(client: TestClient, email: str) -> str:
    body = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert body.status_code == 201, body.text
    return body.json()["access_token"]


def _assert_refused(client: TestClient, url: str, subprotocols=None) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url, subprotocols=subprotocols):
            pass
    assert exc.value.code == WS_UNAUTHENTICATED


def test_socket_without_a_token_is_refused(ws_client: TestClient, monkeypatch) -> None:
    _self_authenticating(monkeypatch)
    _assert_refused(ws_client, "/api/ws/chat/conv-anon")


def test_socket_with_a_garbage_token_is_refused(ws_client: TestClient, monkeypatch) -> None:
    _self_authenticating(monkeypatch)
    _assert_refused(ws_client, "/api/ws/chat/conv-anon", [BEARER, "not-a-token"])


def test_token_offered_under_the_wrong_subprotocol_is_refused(
    ws_client: TestClient, monkeypatch
) -> None:
    _self_authenticating(monkeypatch)
    token = _register(ws_client, "wrongproto@acme.com")
    _assert_refused(ws_client, "/api/ws/chat/conv-anon", ["basic", token])


def test_token_in_the_query_string_is_not_accepted(ws_client: TestClient, monkeypatch) -> None:
    """Query strings reach access logs and browser history, so they are not a credential."""
    _self_authenticating(monkeypatch)
    token = _register(ws_client, "queryparam@acme.com")
    _assert_refused(ws_client, f"/api/ws/chat/conv-anon?token={token}")


def test_socket_refuses_another_users_conversation(ws_client: TestClient, monkeypatch) -> None:
    """Identity used to be a path segment, so anyone could name any conversation."""
    _self_authenticating(monkeypatch)
    alice = _register(ws_client, "alice@acme.com")
    bob = _register(ws_client, "bob@globex.com")

    # Create it over REST so ownership is committed before the socket is tried.
    conversation_id = ws_client.post(
        "/api/conversations", headers={"Authorization": f"Bearer {bob}"}
    ).json()["conversation_id"]

    _assert_refused(ws_client, f"/api/ws/chat/{conversation_id}", [BEARER, alice])

    with ws_client.websocket_connect(
        f"/api/ws/chat/{conversation_id}", subprotocols=[BEARER, bob]
    ) as ws:
        ws.send_json({"message": "mine"})
        assert ws.receive_json()["type"] == "start"


def test_identity_in_the_path_is_no_longer_routable(ws_client: TestClient, monkeypatch) -> None:
    _self_authenticating(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as exc:
        with ws_client.websocket_connect("/api/ws/chat/u1/conv-1"):
            pass
    # Routed to nothing, so it is not the authentication close code.
    assert exc.value.code != WS_UNAUTHENTICATED
