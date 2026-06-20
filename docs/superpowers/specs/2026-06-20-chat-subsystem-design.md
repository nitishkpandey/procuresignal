# SP-1 Design — Chat Subsystem + Backend Hardening

**Date:** 2026-06-20
**Status:** Approved (design)
**Part of:** ProcureSignal Phase-1 MVP completion (SP-1 of 3)

## Context

The PRD/TRD declare Phase-1 "complete," but two subsystems they specify are
absent from the codebase: the AI chat / WebSocket subsystem (FR-7, TRD §4.2)
and the Next.js frontend. The overall completion effort is decomposed into
three sub-projects built in dependency order:

- **SP-1 (this spec):** Backend completion — chat/WebSocket subsystem + structural hardening.
- **SP-2:** Next.js frontend (4 pages: Feed, Article detail, Preferences, Chat).
- **SP-3:** End-to-end integration & verification (full stack boots, smoke test, run docs).

SP-1 must come first because the frontend's chat page depends on the chat API,
and the whole stack needs a clean, running backend.

### Existing patterns this design builds on

- **Models:** subclass `BaseModel` (`shared/procuresignal/models/base.py`) for
  `id`/`created_at`/`updated_at`; JSON columns; indexes via `__table_args__`;
  registered in `shared/procuresignal/models/__init__.py`.
- **Routers:** `APIRouter(prefix="/api", tags=[...])`, `Depends(get_session)`
  from `api/dependencies.py`, Pydantic `response_model` schemas under `api/schemas/`.
- **Groq:** `GroqLLMClient` (`shared/procuresignal/enrichment/groq_client.py`) is
  single-shot (`stream=False`) for enrichment. Chat needs streaming and is kept
  separate to avoid disturbing the working enrichment path.
- **Feed/preferences access:** `feed.py` joins `UserNewsFeed → NewsArticleProcessed
  → NewsArticleRaw`; `PreferenceManager.get_preference()` loads `UserNewsPreference`.

## Goals

- Add persistent chat conversations & messages.
- Provide a context-aware, streaming WebSocket chat grounded in the user's
  preferences and recent feed.
- Provide REST endpoints so the frontend can list/read chat history and start
  conversations.
- Clean up structural cruft (`api/api/`, `worker/worker/`) to one consistent layout.
- Full test suite green; API boots with the new routes visible in `/docs`.

## Non-Goals (YAGNI)

- Authentication / login — Phase 2 per PRD. `user_id` remains a trusted path string.
- Vector search / ChromaDB RAG over full articles — TRD lists this as a future phase.
- Rate limiting / quotas — Phase 2.

## Design

### 1. Data models — `shared/procuresignal/models/chat.py`

**`ChatConversation`** (`chat_conversations`)
- `user_id: str` (String 100, not null)
- `conversation_id: str` (String 100, unique, not null) — UUID string
- `title: str | None` (String 200) — auto-set from the first user message (truncated)
- `message_count: int` (default 0)
- `last_message_at: datetime | None` (DateTime, nullable)
- Indexes: `(user_id, last_message_at)`; unique on `conversation_id`.

**`ChatMessage`** (`chat_messages`)
- `user_id: str` (String 100, not null)
- `conversation_id: str` (String 100, not null)
- `role: str` (String 20) — `"user"` or `"assistant"`
- `content: str` (Text, not null)
- `tokens_used: int | None`
- Indexes: `(conversation_id, created_at)`.

Both registered in `models/__init__.py` (`__all__`). One Alembic migration adds
both tables, matching the style in `migrations/versions/`.

### 2. Chat context builder — `shared/procuresignal/chat/context.py`

Pure async function `build_system_prompt(session, user_id) -> str`:
- Loads `UserNewsPreference` via `PreferenceManager.get_preference`.
- Loads top ~10 recent feed rows (same join `feed.py` uses), extracting
  title + summary + signal tags.
- Composes a system prompt: procurement-analyst persona + the user's followed
  suppliers/regions/categories/signals + a compact digest of recent articles +
  instruction to answer grounded in that context.
- **Degradation:** with no preferences/feed, returns a generic analyst prompt
  (no crash, no empty sections).

### 3. Streaming Groq chat client — `shared/procuresignal/chat/chat_client.py`

`ChatLLMClient` using `AsyncGroq` with `stream=True`:
- `stream_chat(system_prompt, history, user_message) -> AsyncIterator[str]`
  yields text deltas.
- `history` is the prior conversation messages (role/content) for multi-turn.
- Tracks `tokens_used` for the completed response (from the final usage chunk
  when available; otherwise best-effort estimate of 0/None).
- Same model as enrichment (`llama-3.1-8b-instant`); higher `max_tokens` suitable
  for chat; reuses `GROQ_API_KEY`.
- Kept separate from `GroqLLMClient`; enrichment is untouched.

### 4. WebSocket endpoint — `api/routers/chat.py`

`WS /api/ws/chat/{user_id}/{conversation_id}` implementing TRD §4.2:
1. On connect: `accept()`; ensure the `ChatConversation` row exists (create if new).
2. On each inbound `{"message": "..."}`:
   - Persist a `user` `ChatMessage`.
   - On first user message, set conversation `title` from it (truncated).
   - Build system prompt (§2); load prior messages as history.
   - Send `{"type":"start","content":"Processing your message..."}`.
   - Stream deltas as `{"type":"stream","content":"<delta>"}`.
   - Send `{"type":"end","content":"Response complete"}`.
   - Persist the assembled `assistant` `ChatMessage` + `tokens_used`; update
     `message_count` and `last_message_at`.
3. Errors (Groq/DB): send `{"type":"error","content":"<message>"}`; keep the
   socket open.
4. On `WebSocketDisconnect`: clean exit.

Uses a session acquired from `database.db_config.session_maker` (WebSocket routes
can't use the HTTP `Depends(get_session)` generator cleanly for long-lived
connections; a short-lived session is opened per inbound message).

### 5. Chat history REST endpoints — `api/routers/chat.py`

- `POST /api/conversations?user_id=` → create an empty conversation; returns a
  fresh `conversation_id` (UUID) + metadata. Lets the UI open a chat before the
  first WS message.
- `GET /api/conversations?user_id=` → list conversations ordered by
  `last_message_at` desc (id, conversation_id, title, message_count, last_message_at).
- `GET /api/conversations/{conversation_id}/messages` → messages ordered by
  `created_at` asc (role, content, created_at, tokens_used).

Pydantic schemas in `api/schemas/chat.py`. Router registered in `main.py`.

### 6. Structural cleanup

- Move `api/api/routers/signals.py` → `api/routers/signals.py`; update the import
  in `api/main.py`; delete the now-empty nested `api/api/` tree.
- Delete the empty `worker/worker/` stub tree.
- No behavior change to existing endpoints — pure consolidation to one layout.

### 7. Error handling

- Missing `GROQ_API_KEY`: WS sends an `error` frame explaining chat is
  unavailable rather than crashing the connection.
- DB not initialized: history endpoints return 503 (consistent with
  `get_session`); WS sends an `error` frame.
- Malformed inbound payload (missing `message`): `error` frame, socket stays open.

## Testing Strategy (definition of done)

- **Unit:** context builder (with and without preferences/feed); chat models;
  history endpoints (create/list/get) against the test DB; conversation/message
  persistence and counters.
- **WebSocket:** `TestClient.websocket_connect` test sending a message and
  asserting the `start → stream* → end` frame sequence with a stubbed
  `ChatLLMClient`, plus that user+assistant messages persist and counters update.
- **Regression:** full existing suite stays green; structural move of the signals
  router keeps `/api` signals routes working.
- **Boot check:** `uvicorn api.main:app` imports and exposes the new routes in
  `/docs`.

## File-Level Change Summary

New:
- `shared/procuresignal/models/chat.py`
- `shared/procuresignal/chat/__init__.py`, `context.py`, `chat_client.py`
- `api/routers/chat.py`, `api/schemas/chat.py`
- `migrations/versions/<rev>_add_chat_tables.py`
- `tests/unit/test_chat.py`, `tests/integration/test_chat_ws.py`

Modified:
- `shared/procuresignal/models/__init__.py` (register chat models)
- `api/main.py` (import signals from new path; register chat router)

Moved/removed:
- `api/api/routers/signals.py` → `api/routers/signals.py`; delete `api/api/`
- delete `worker/worker/`
