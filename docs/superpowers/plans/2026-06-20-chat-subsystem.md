# Chat Subsystem + Backend Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a context-aware, streaming WebSocket AI chat subsystem (with persistent history and REST access) to the ProcureSignal backend, and consolidate the duplicated `api/api/` and `worker/worker/` directory cruft into one consistent layout.

**Architecture:** Two new SQLAlchemy models (`ChatConversation`, `ChatMessage`) + an Alembic migration. A pure context builder assembles a system prompt from the user's preferences and recent feed. A separate `AsyncGroq`-based streaming client produces the assistant reply (the existing single-shot enrichment `GroqLLMClient` is left untouched). A new `api/routers/chat.py` exposes REST history endpoints plus a `WS /api/ws/chat/{user_id}/{conversation_id}` endpoint that persists messages and streams `start → stream* → end` frames per TRD §4.2.

**Tech Stack:** Python 3.11, FastAPI, Starlette WebSockets, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, Groq SDK (`AsyncGroq`), pytest (`asyncio_mode = "auto"`), in-memory SQLite (`aiosqlite`) for tests.

## Global Constraints

- Canonical package imports are `from procuresignal...` (package `procuresignal` is installed from `shared/`). Do NOT use `from shared.procuresignal...`.
- All models subclass `BaseModel` from `procuresignal.models.base` (provides `id`, `created_at`, `updated_at`) and register in `shared/procuresignal/models/__init__.py` `__all__`.
- API routers use `APIRouter(prefix="/api", tags=[...])` and `Depends(get_session)` from `api.dependencies`; response models are Pydantic classes under `api/schemas/`.
- Pydantic response schemas reading from ORM objects use `model_config = ConfigDict(from_attributes=True)`.
- The WebSocket handler must obtain DB sessions from `procuresignal.config.database.db_config.session_maker` (HTTP `Depends(get_session)` is not used for the long-lived socket).
- No authentication — `user_id` is a trusted path/query string (Phase 1, per PRD).
- Tests use in-memory SQLite seeded via `Base.metadata.create_all`; the LLM is always stubbed in tests (never call Groq).
- Each task ends green: run the listed tests and the full suite before committing.
- Current Alembic head is `1a2b3c_add_signals_tables`.

---

### Task 1: Chat models + registration

**Files:**
- Create: `shared/procuresignal/models/chat.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Test: `tests/unit/test_chat_models.py`

**Interfaces:**
- Produces: `ChatConversation` (cols: `id`, `user_id: str`, `conversation_id: str` unique, `title: str|None`, `message_count: int`, `last_message_at: datetime|None`, `created_at`, `updated_at`); `ChatMessage` (cols: `id`, `user_id: str`, `conversation_id: str`, `role: str`, `content: str`, `tokens_used: int|None`, `created_at`, `updated_at`). Both importable from `procuresignal.models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_chat_models.py
"""Tests for chat models."""

from procuresignal.models import ChatConversation, ChatMessage


def test_chat_conversation_table_and_columns():
    assert ChatConversation.__tablename__ == "chat_conversations"
    cols = {c.name for c in ChatConversation.__table__.columns}
    assert {
        "id",
        "user_id",
        "conversation_id",
        "title",
        "message_count",
        "last_message_at",
        "created_at",
        "updated_at",
    } <= cols


def test_chat_conversation_id_is_unique():
    assert ChatConversation.__table__.c.conversation_id.unique is True


def test_chat_message_table_and_columns():
    assert ChatMessage.__tablename__ == "chat_messages"
    cols = {c.name for c in ChatMessage.__table__.columns}
    assert {"id", "user_id", "conversation_id", "role", "content", "tokens_used"} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/test_chat_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ChatConversation'`

- [ ] **Step 3: Write the models**

```python
# shared/procuresignal/models/chat.py
"""Chat conversation and message models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ChatConversation(BaseModel):
    """A chat conversation thread for a user."""

    __tablename__ = "chat_conversations"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_chat_conversations_user_last", "user_id", "last_message_at"),
    )


class ChatMessage(BaseModel):
    """A single message within a chat conversation."""

    __tablename__ = "chat_messages"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_chat_messages_conv_created", "conversation_id", "created_at"),
    )
```

- [ ] **Step 4: Register the models**

In `shared/procuresignal/models/__init__.py`, add the import and `__all__` entries (place the import line alphabetically near the others, after the `.base` import):

```python
from .chat import ChatConversation, ChatMessage
```

And add to `__all__`:

```python
    "ChatConversation",
    "ChatMessage",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/unit/test_chat_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add shared/procuresignal/models/chat.py shared/procuresignal/models/__init__.py tests/unit/test_chat_models.py
git commit -m "feat(chat): add ChatConversation and ChatMessage models"
```

---

### Task 2: Alembic migration for chat tables

**Files:**
- Create: `migrations/versions/a1b2c3_add_chat_tables.py`

**Interfaces:**
- Consumes: current head `1a2b3c_add_signals_tables`.
- Produces: tables `chat_conversations`, `chat_messages` in PostgreSQL.

This task has no pytest test (the test suite uses `create_all`, not migrations). Verify by Alembic offline SQL generation.

- [ ] **Step 1: Write the migration**

```python
# migrations/versions/a1b2c3_add_chat_tables.py
"""add chat tables

Revision ID: a1b2c3_add_chat_tables
Revises: 1a2b3c_add_signals_tables
Create Date: 2026-06-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3_add_chat_tables"
down_revision = "1a2b3c_add_signals_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("conversation_id", name="uq_chat_conversations_conversation_id"),
    )
    op.create_index(
        "idx_chat_conversations_user_last",
        "chat_conversations",
        ["user_id", "last_message_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_chat_messages_conv_created",
        "chat_messages",
        ["conversation_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_chat_messages_conv_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("idx_chat_conversations_user_last", table_name="chat_conversations")
    op.drop_table("chat_conversations")
```

- [ ] **Step 2: Verify single head and offline SQL generation**

Run: `poetry run alembic heads`
Expected: exactly one head — `a1b2c3_add_chat_tables (head)`

Run: `poetry run alembic upgrade 1a2b3c_add_signals_tables:a1b2c3_add_chat_tables --sql`
Expected: emits `CREATE TABLE chat_conversations` and `CREATE TABLE chat_messages` SQL with no errors.

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/a1b2c3_add_chat_tables.py
git commit -m "feat(chat): add alembic migration for chat tables"
```

---

### Task 3: Chat context builder

**Files:**
- Create: `shared/procuresignal/chat/__init__.py`
- Create: `shared/procuresignal/chat/context.py`
- Test: `tests/unit/test_chat_context.py`

**Interfaces:**
- Consumes: `PreferenceManager.get_preference(session, user_id)`; `UserNewsFeed`, `NewsArticleProcessed` models.
- Produces: `async build_system_prompt(session: AsyncSession, user_id: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_chat_context.py
"""Tests for the chat context builder."""

import asyncio
from datetime import datetime

from procuresignal.chat.context import build_system_prompt
from procuresignal.models import (
    Base,
    NewsArticleProcessed,
    NewsArticleRaw,
    UserNewsFeed,
    UserNewsPreference,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _make_session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return asyncio.run(setup())


def test_prompt_without_preferences_is_generic():
    maker = _make_session_maker()

    async def run():
        async with maker() as session:
            return await build_system_prompt(session, "nobody")

    prompt = asyncio.run(run())
    assert "procurement" in prompt.lower()
    assert isinstance(prompt, str) and len(prompt) > 0


def test_prompt_includes_preferences_and_articles():
    maker = _make_session_maker()

    async def run():
        async with maker() as session:
            raw = NewsArticleRaw(
                provider="newsapi",
                provider_article_id="a1",
                query_group="supplier_risk",
                ingest_hash="h1",
                title="Bosch strike in Poland",
                description="d",
                content_snippet="c",
                article_url="https://e.com/a",
                canonical_url="https://e.com/a",
                source_name="Reuters",
                source_url="https://reuters.com",
                published_at=datetime.utcnow(),
                language="en",
                ingested_at=datetime.utcnow(),
            )
            session.add(raw)
            await session.flush()
            processed = NewsArticleProcessed(
                raw_article_id=raw.id,
                normalized_title="Bosch strike Poland",
                summary="Workers at Bosch began a strike.",
                top_level_category="automotive",
                signal_tags=["strike"],
                priority_signal="strike",
                detected_regions=["Poland"],
                detected_suppliers=["Bosch"],
                detected_categories=["automotive"],
                signal_score=0.9,
                processing_status="completed",
                llm_model="test",
                language="en",
                processed_at=datetime.utcnow(),
            )
            session.add(processed)
            await session.flush()
            session.add(
                UserNewsFeed(
                    user_id="u1",
                    processed_article_id=processed.id,
                    top_level_category="automotive",
                    rank_score=0.9,
                    match_reasons={},
                    surfaced_at=datetime.utcnow(),
                )
            )
            session.add(
                UserNewsPreference(
                    user_id="u1",
                    preferred_categories=["automotive"],
                    preferred_suppliers=["Bosch"],
                    preferred_regions=["Poland"],
                    preferred_signals=["strike"],
                    excluded_categories=[],
                    excluded_suppliers=[],
                    excluded_regions=[],
                    excluded_signals=[],
                    excluded_topics=[],
                    onboarding_completed=True,
                )
            )
            await session.commit()
            return await build_system_prompt(session, "u1")

    prompt = asyncio.run(run())
    assert "Bosch" in prompt
    assert "Bosch strike Poland" in prompt
    assert "strike" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/test_chat_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'procuresignal.chat'`

- [ ] **Step 3: Create the package and context builder**

```python
# shared/procuresignal/chat/__init__.py
"""Chat subsystem (context builder + streaming LLM client)."""
```

```python
# shared/procuresignal/chat/context.py
"""Assemble the chat system prompt from user preferences and recent feed."""

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleProcessed, UserNewsFeed
from procuresignal.personalization import PreferenceManager

_BASE_PERSONA = (
    "You are ProcureSignal, an AI procurement intelligence analyst. "
    "You help supply chain and procurement professionals understand news about "
    "suppliers, regions, tariffs, strikes, and supply-chain risks. "
    "Be concise, factual, and actionable. If you are unsure, say so."
)

_RECENT_ARTICLE_LIMIT = 10


async def _recent_articles(session: AsyncSession, user_id: str) -> list[tuple[str, str, list]]:
    stmt = (
        select(
            NewsArticleProcessed.normalized_title,
            NewsArticleProcessed.summary,
            NewsArticleProcessed.signal_tags,
        )
        .join(UserNewsFeed, UserNewsFeed.processed_article_id == NewsArticleProcessed.id)
        .where(UserNewsFeed.user_id == user_id)
        .where(UserNewsFeed.is_hidden.is_(False))
        .order_by(desc(UserNewsFeed.surfaced_at))
        .limit(_RECENT_ARTICLE_LIMIT)
    )
    result = await session.execute(stmt)
    return [(title, summary, tags or []) for title, summary, tags in result.all()]


async def build_system_prompt(session: AsyncSession, user_id: str) -> str:
    """Build a context-aware system prompt for the user's chat session."""

    parts: list[str] = [_BASE_PERSONA]

    pref = await PreferenceManager.get_preference(session, user_id)
    if pref is not None:
        focus: list[str] = []
        if pref.preferred_suppliers:
            focus.append(f"Suppliers: {', '.join(pref.preferred_suppliers)}")
        if pref.preferred_regions:
            focus.append(f"Regions: {', '.join(pref.preferred_regions)}")
        if pref.preferred_categories:
            focus.append(f"Categories: {', '.join(pref.preferred_categories)}")
        if pref.preferred_signals:
            focus.append(f"Signals: {', '.join(pref.preferred_signals)}")
        if focus:
            parts.append("The user follows — " + "; ".join(focus) + ".")

    articles = await _recent_articles(session, user_id)
    if articles:
        digest = "\n".join(
            f"- {title} [{', '.join(tags) if tags else 'no tags'}]: {summary}"
            for title, summary, tags in articles
        )
        parts.append("Recent relevant articles in the user's feed:\n" + digest)

    parts.append("Answer the user's questions grounded in this context when relevant.")
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/unit/test_chat_context.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add shared/procuresignal/chat/__init__.py shared/procuresignal/chat/context.py tests/unit/test_chat_context.py
git commit -m "feat(chat): add context builder grounded in preferences and feed"
```

---

### Task 4: Streaming Groq chat client

**Files:**
- Create: `shared/procuresignal/chat/chat_client.py`
- Test: `tests/unit/test_chat_client.py`

**Interfaces:**
- Produces: `ChatLLMClient` with `MODEL`, `MAX_TOKENS`, attribute `last_tokens_used: int`, and `async stream_chat(system_prompt: str, history: list[dict], user_message: str) -> AsyncIterator[str]`. Constructor raises `ValueError` if no API key. `history` items are `{"role": str, "content": str}`.

The test stubs the underlying `AsyncGroq` client so no network call happens. It validates message assembly and that deltas are yielded.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_chat_client.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/test_chat_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'procuresignal.chat.chat_client'`

- [ ] **Step 3: Write the client**

```python
# shared/procuresignal/chat/chat_client.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/unit/test_chat_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Verify the AsyncGroq import resolves**

Run: `poetry run python -c "from groq import AsyncGroq; print('ok')"`
Expected: prints `ok`. (If it fails, the installed `groq` version is too old; run `poetry add groq@latest` and re-run.)

- [ ] **Step 6: Commit**

```bash
git add shared/procuresignal/chat/chat_client.py tests/unit/test_chat_client.py
git commit -m "feat(chat): add streaming AsyncGroq chat client"
```

---

### Task 5: Chat REST schemas + history endpoints

**Files:**
- Create: `api/schemas/chat.py`
- Create: `api/routers/chat.py` (REST endpoints only in this task; WebSocket added in Task 6)
- Modify: `api/main.py`
- Test: `tests/integration/test_chat_api.py`

**Interfaces:**
- Consumes: `ChatConversation`, `ChatMessage` models; `get_session` dependency.
- Produces: REST routes `POST /api/conversations`, `GET /api/conversations`, `GET /api/conversations/{conversation_id}/messages`; schemas `ConversationResponse`, `ConversationListResponse`, `MessageResponse`, `MessageListResponse`; router object `router` in `api.routers.chat`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_chat_api.py
"""Integration tests for chat REST endpoints."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app


@pytest.fixture()
def chat_client():
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_chat_api.py -v`
Expected: FAIL (404 routes not found → assertion/`405`/`404` on POST, ultimately import or routing failure once router referenced). Initially fails because `api.routers.chat` does not exist.

- [ ] **Step 3: Write the schemas**

```python
# api/schemas/chat.py
"""Chat request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    title: Optional[str] = None
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ConversationListResponse(BaseModel):
    user_id: str
    conversations: list[ConversationResponse]
    total_count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    tokens_used: Optional[int] = None
    created_at: Optional[datetime] = None


class MessageListResponse(BaseModel):
    conversation_id: str
    messages: list[MessageResponse]
    total_count: int
```

- [ ] **Step 4: Write the REST router**

```python
# api/routers/chat.py
"""Chat REST + WebSocket endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import ChatConversation, ChatMessage
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.chat import (
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api", tags=["chat"])


async def _get_conversation(session: AsyncSession, conversation_id: str) -> ChatConversation | None:
    return await session.scalar(
        select(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
    )


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    """Create a new, empty conversation and return its generated id."""

    conversation = ChatConversation(
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        title=None,
        message_count=0,
        last_message_at=None,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ConversationListResponse:
    """List a user's conversations, most recently active first."""

    rows = (
        await session.scalars(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(desc(ChatConversation.last_message_at), desc(ChatConversation.created_at))
        )
    ).all()
    return ConversationListResponse(
        user_id=user_id,
        conversations=[ConversationResponse.model_validate(r) for r in rows],
        total_count=len(rows),
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def get_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> MessageListResponse:
    """Return the ordered messages of a conversation."""

    conversation = await _get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    rows = (
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(asc(ChatMessage.created_at), asc(ChatMessage.id))
        )
    ).all()
    return MessageListResponse(
        conversation_id=conversation_id,
        messages=[MessageResponse.model_validate(r) for r in rows],
        total_count=len(rows),
    )
```

- [ ] **Step 5: Register the router in main.py**

In `api/main.py`, add `chat` to the routers import line:

```python
from api.routers import articles, chat, feed, health, preferences
```

And register it (after `preferences`):

```python
app.include_router(chat.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `poetry run pytest tests/integration/test_chat_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add api/schemas/chat.py api/routers/chat.py api/main.py tests/integration/test_chat_api.py
git commit -m "feat(chat): add conversation/message REST endpoints"
```

---

### Task 6: WebSocket chat endpoint

**Files:**
- Modify: `api/routers/chat.py`
- Test: `tests/integration/test_chat_ws.py`

**Interfaces:**
- Consumes: `ChatLLMClient` (Task 4), `build_system_prompt` (Task 3), `database.db_config.session_maker`, `ChatConversation`/`ChatMessage`.
- Produces: route `WS /api/ws/chat/{user_id}/{conversation_id}`; module-level factory `_build_chat_client() -> ChatLLMClient` (overridable in tests). Frame protocol: `{"type":"start"|"stream"|"end"|"error","content": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_chat_ws.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_chat_ws.py -v`
Expected: FAIL (no `_build_chat_client` attribute / no WS route → `WebSocketDisconnect` / `AttributeError`).

- [ ] **Step 3: Add the WebSocket endpoint to `api/routers/chat.py`**

Add these imports to the existing import block at the top of `api/routers/chat.py`:

```python
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from procuresignal.chat.chat_client import ChatLLMClient
from procuresignal.chat.context import build_system_prompt
from procuresignal.config import database
```

Append to the end of `api/routers/chat.py`:

```python
def _build_chat_client() -> ChatLLMClient:
    """Factory for the streaming chat client (overridable in tests)."""

    return ChatLLMClient()


async def _ensure_conversation(session_maker, user_id: str, conversation_id: str) -> None:
    async with session_maker() as session:
        conversation = await _get_conversation(session, conversation_id)
        if conversation is None:
            session.add(
                ChatConversation(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title=None,
                    message_count=0,
                    last_message_at=None,
                )
            )
            await session.commit()


async def _persist_user_message(
    session_maker, user_id: str, conversation_id: str, text: str
) -> tuple[str, list[dict]]:
    """Persist the user message, set title if first, return (system_prompt, history)."""

    async with session_maker() as session:
        session.add(
            ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role="user",
                content=text,
                tokens_used=None,
            )
        )
        conversation = await _get_conversation(session, conversation_id)
        if conversation is not None and not conversation.title:
            conversation.title = text[:200]
        await session.commit()

        history_rows = (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(asc(ChatMessage.created_at), asc(ChatMessage.id))
            )
        ).all()
        history = [{"role": m.role, "content": m.content} for m in history_rows[:-1]]
        system_prompt = await build_system_prompt(session, user_id)
    return system_prompt, history


async def _persist_assistant_message(
    session_maker, user_id: str, conversation_id: str, text: str, tokens_used: int | None
) -> None:
    async with session_maker() as session:
        session.add(
            ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=text,
                tokens_used=tokens_used,
            )
        )
        conversation = await _get_conversation(session, conversation_id)
        if conversation is not None:
            conversation.message_count = (conversation.message_count or 0) + 2
            conversation.last_message_at = datetime.utcnow()
        await session.commit()


@router.websocket("/ws/chat/{user_id}/{conversation_id}")
async def chat_websocket(websocket: WebSocket, user_id: str, conversation_id: str) -> None:
    """Stream a context-aware chat response, persisting both sides of the exchange."""

    await websocket.accept()

    session_maker = getattr(database.db_config, "session_maker", None) if database.db_config else None
    if session_maker is None:
        await websocket.send_json({"type": "error", "content": "Database not initialized"})
        await websocket.close()
        return

    try:
        client = _build_chat_client()
    except ValueError:
        await websocket.send_json(
            {"type": "error", "content": "Chat is unavailable: GROQ_API_KEY not configured"}
        )
        await websocket.close()
        return

    await _ensure_conversation(session_maker, user_id, conversation_id)

    try:
        while True:
            payload = await websocket.receive_json()
            user_message = (payload or {}).get("message")
            if not user_message:
                await websocket.send_json(
                    {"type": "error", "content": "Missing 'message' field"}
                )
                continue

            try:
                system_prompt, history = await _persist_user_message(
                    session_maker, user_id, conversation_id, user_message
                )
                await websocket.send_json(
                    {"type": "start", "content": "Processing your message..."}
                )
                chunks: list[str] = []
                async for delta in client.stream_chat(system_prompt, history, user_message):
                    chunks.append(delta)
                    await websocket.send_json({"type": "stream", "content": delta})
                await websocket.send_json({"type": "end", "content": "Response complete"})

                await _persist_assistant_message(
                    session_maker,
                    user_id,
                    conversation_id,
                    "".join(chunks),
                    getattr(client, "last_tokens_used", None),
                )
            except Exception as exc:  # noqa: BLE001 — surface to client, keep socket open
                await websocket.send_json(
                    {"type": "error", "content": f"Failed to process message: {exc}"}
                )
    except WebSocketDisconnect:
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/integration/test_chat_ws.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/routers/chat.py tests/integration/test_chat_ws.py
git commit -m "feat(chat): add streaming websocket chat endpoint with persistence"
```

---

### Task 7: Structural cleanup (relocate signals router, delete cruft)

**Files:**
- Move: `api/api/routers/signals.py` → `api/routers/signals.py` (and normalize imports)
- Modify: `api/main.py`
- Delete: `api/api/` tree, `worker/worker/` tree
- Test: `tests/integration/test_signals_route.py`

**Interfaces:**
- Produces: `router` in `api.routers.signals` (prefix `/api/signals`), registered in `main.py`. Same routes as before, now under the canonical layout.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_signals_route.py
"""Verify the signals router is reachable from the canonical location."""

from api.routers.signals import router as signals_router


def test_signals_router_prefix_and_routes():
    assert signals_router.prefix == "/api/signals"
    paths = {route.path for route in signals_router.routes}
    assert "/api/signals/" in paths
    assert "/api/signals/stats/summary" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_signals_route.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.routers.signals'`

- [ ] **Step 3: Move the file and normalize imports**

```bash
git mv api/api/routers/signals.py api/routers/signals.py
```

In `api/routers/signals.py`, change the three `shared.procuresignal` imports to the canonical form:

```python
from procuresignal.config import database
from procuresignal.models import Signal as SignalModel
from procuresignal.models import SignalMetadata
```

- [ ] **Step 4: Update main.py to import from the new location**

In `api/main.py`, delete this line:

```python
from api.api.routers.signals import router as signals_router
```

Add `signals` to the canonical routers import line:

```python
from api.routers import articles, chat, feed, health, preferences, signals
```

Change the registration line from:

```python
app.include_router(signals_router)
```

to:

```python
app.include_router(signals.router)
```

- [ ] **Step 5: Delete the cruft directories**

```bash
git rm -r api/api worker/worker
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `poetry run pytest tests/integration/test_signals_route.py tests/integration/test_chat_api.py -v`
Expected: PASS (both files green; the app still imports and registers signals)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(api): consolidate signals router and remove duplicated dir cruft"
```

---

### Task 8: Full-suite verification + boot check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `poetry run pytest -q`
Expected: all tests pass (existing + the new chat/signals tests), no errors.

- [ ] **Step 2: Lint and format gates (repo standard)**

Run: `poetry run ruff check . && poetry run black --check .`
Expected: no violations. (If Black reports files, run `poetry run black .` and re-commit.)

- [ ] **Step 3: Boot check — app imports and exposes the new routes**

Run:
```bash
poetry run python -c "from api.main import app; paths=[r.path for r in app.routes]; assert '/api/conversations' in paths; assert any('/ws/chat' in p for p in paths); assert any('/api/signals' in p for p in paths); print('routes ok:', sorted(p for p in paths if 'chat' in p or 'signals' in p or 'conversations' in p))"
```
Expected: prints `routes ok: [...]` including `/api/ws/chat/{user_id}/{conversation_id}`, `/api/conversations`, and `/api/signals/...`.

- [ ] **Step 4: Commit any formatting fixups (if Step 2 changed files)**

```bash
git add -A
git commit -m "chore(chat): apply formatting and finalize chat subsystem"
```

---

## Definition of Done (SP-1)

- `chat_conversations` / `chat_messages` models + migration exist; migration has a single Alembic head.
- Context builder grounds the system prompt in preferences + recent feed and degrades cleanly with neither.
- Streaming `ChatLLMClient` assembles system+history+user messages and yields deltas (enrichment path untouched).
- REST endpoints create/list conversations and fetch messages; WebSocket streams `start → stream* → end`, persists user+assistant messages, updates `message_count`/`last_message_at`/`title`, and surfaces errors without dropping the socket.
- Signals router lives at `api/routers/signals.py`; `api/api/` and `worker/worker/` cruft removed.
- Full test suite, ruff, and black all green; the app boots and exposes the new routes.
