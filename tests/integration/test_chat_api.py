"""Integration tests for chat REST endpoints."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.models import Base, ChatMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app


@pytest.fixture()
def chat_client(monkeypatch):
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

    async def override_get_session():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    database_module.db_config = original
    asyncio.run(engine.dispose())


def test_create_and_list_conversation(chat_client: TestClient):
    created = chat_client.post("/api/conversations", params={"user_id": "u1"})
    assert created.status_code == 200
    conv_id = created.json()["conversation_id"]
    assert conv_id

    listed = chat_client.get("/api/conversations", params={"user_id": "u1"})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total_count"] == 1
    assert payload["conversations"][0]["conversation_id"] == conv_id


def test_messages_for_unknown_conversation_404(chat_client: TestClient):
    resp = chat_client.get("/api/conversations/does-not-exist/messages")
    assert resp.status_code == 404


def test_clear_conversation_history_deletes_user_conversations(chat_client: TestClient):
    first = chat_client.post("/api/conversations", params={"user_id": "u1"})
    second = chat_client.post("/api/conversations", params={"user_id": "u1"})
    other = chat_client.post("/api/conversations", params={"user_id": "u2"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert other.status_code == 200

    deleted = chat_client.delete("/api/conversations", params={"user_id": "u1"})

    assert deleted.status_code == 200
    assert deleted.json() == {
        "user_id": "u1",
        "deleted_conversations": 2,
        "deleted_messages": 0,
    }
    listed = chat_client.get("/api/conversations", params={"user_id": "u1"})
    assert listed.json()["conversations"] == []
    other_listed = chat_client.get("/api/conversations", params={"user_id": "u2"})
    assert other_listed.json()["total_count"] == 1


def test_clear_conversation_history_deletes_messages(chat_client: TestClient):
    created = chat_client.post("/api/conversations", params={"user_id": "u1"})
    conv_id = created.json()["conversation_id"]

    async def add_message():
        session_maker = database_module.db_config.session_maker
        async with session_maker() as session:
            session.add(
                ChatMessage(
                    user_id="u1",
                    conversation_id=conv_id,
                    role="user",
                    content="hello",
                    tokens_used=None,
                )
            )
            await session.commit()

    asyncio.run(add_message())

    deleted = chat_client.delete("/api/conversations", params={"user_id": "u1"})

    assert deleted.status_code == 200
    assert deleted.json()["deleted_messages"] == 1
