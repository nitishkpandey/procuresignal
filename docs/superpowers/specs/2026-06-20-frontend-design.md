# SP-2 Design — Next.js Frontend

**Date:** 2026-06-20
**Status:** Approved (design)
**Part of:** ProcureSignal Phase-1 MVP completion (SP-2 of 3)

## Context

SP-1 completed the backend (chat subsystem + hardening). SP-2 builds the
frontend the PRD/TRD claim exists but does not: a Next.js app with four pages
(Feed, Article detail, Preferences, Chat). SP-3 will wire the frontend into
docker-compose and run a full-stack smoke test.

The backend exposes these endpoints (confirmed in code during SP-1):

- `GET /api/feed?user_id=&limit=&days=` → `{ user_id, articles[], total_count, generated_at, days_included }`
- `GET /api/search?q=&limit=&days=` → `{ query, total_results, results[], search_time_ms }`
- `GET /api/articles/{id}` → full `ArticleDetail`
- `POST /api/articles/{id}/read?user_id=` → `{ article_id, user_id, read }`
- `GET /api/preferences?user_id=` / `POST /api/preferences` → preference object
- `POST /api/conversations?user_id=` → `{ conversation_id, title, message_count, last_message_at, created_at }`
- `GET /api/conversations?user_id=` → `{ user_id, conversations[], total_count }`
- `GET /api/conversations/{conversation_id}/messages` → `{ conversation_id, messages[], total_count }`
- `WS /api/ws/chat/{user_id}/{conversation_id}` → frames `{ type: "start"|"stream"|"end"|"error", content }`; client sends `{ message }`

## Goals

- Four working, mobile-responsive pages consuming the live API.
- Streaming chat over WebSocket with conversation history.
- Clear loading / error / empty states throughout.
- Verifiable without a live backend: Vitest + RTL tests (backend mocked),
  `tsc --noEmit`, ESLint, and a successful `next build`.

## Non-Goals (YAGNI)

- Authentication / login — Phase 2. Identity is a plain `user_id` string.
- Server-side rendering of data — client-side fetching is simpler given the
  localStorage identity.
- A global data-fetching library (React Query/SWR) — a small `useApi` hook suffices.
- A component generator / design system (shadcn CLI) — hand-rolled Tailwind
  components in the shadcn aesthetic.
- Docker/compose wiring and full-stack E2E — SP-3.

## Tech Stack

Next.js 14 (App Router), TypeScript 5, Tailwind CSS 3, Zustand (persisted),
Axios, native browser WebSocket, Vitest + React Testing Library + jsdom, ESLint
(`next lint`). Node 18+.

## Architecture

A standalone `frontend/` package at the repo root. Pages are client components
that read `user_id` from a Zustand store and fetch via a typed Axios client.
Chat uses a thin WebSocket wrapper plus a pure reducer that folds streamed
frames into the live assistant message.

### Directory layout

```
frontend/
  package.json, tsconfig.json, next.config.mjs, tailwind.config.ts,
  postcss.config.mjs, .eslintrc.json, vitest.config.ts, vitest.setup.ts,
  .env.example, .env.local (gitignored)
  app/
    layout.tsx              # root layout: <Header/> + children
    globals.css             # tailwind directives
    page.tsx                # Feed (+ integrated search)
    articles/[id]/page.tsx  # Article detail
    preferences/page.tsx    # Preferences
    chat/page.tsx           # Chat
  components/
    ui/{button,card,badge,input,textarea,spinner,empty-state}.tsx
    header.tsx              # nav + editable user_id
    article-card.tsx
    signal-badge.tsx
    feed-list.tsx
    search-bar.tsx
    preference-form.tsx
    conversation-list.tsx
    chat-window.tsx
  lib/
    types.ts               # TS mirrors of API shapes + WS frame
    api.ts                 # typed Axios client functions
    ws.ts                  # WebSocket wrapper for chat
    chatReducer.ts         # pure frame-folding reducer
    useApi.ts              # generic fetch hook (loading/error/data)
  store/
    user.ts                # Zustand store, user_id persisted to localStorage
  __tests__/               # Vitest + RTL specs
```

### Modules and responsibilities

- **`lib/types.ts`** — `Article`, `FeedArticle`, `FeedResponse`, `ArticleDetail`,
  `SearchResult`, `SearchResponse`, `Preferences`, `Conversation`, `Message`,
  `ChatFrame` interfaces matching the backend schemas.
- **`lib/api.ts`** — one Axios instance (`baseURL = NEXT_PUBLIC_API_URL`) and
  typed functions: `getFeed`, `search`, `getArticle`, `markRead`,
  `getPreferences`, `savePreferences`, `listConversations`, `createConversation`,
  `getMessages`. Each returns typed data; errors propagate to callers.
- **`lib/ws.ts`** — `openChatSocket(userId, conversationId, handlers)` returning a
  `{ send(message), close() }` handle; parses inbound JSON into `ChatFrame` and
  dispatches to `onFrame`/`onOpen`/`onClose`/`onError`. Reads `NEXT_PUBLIC_WS_URL`.
- **`lib/chatReducer.ts`** — `chatReducer(state, frame)` pure function: `start`
  appends an empty assistant message and marks streaming; `stream` appends
  `content` to the last assistant message; `end` clears streaming; `error`
  records an error string. Unit-tested without any socket.
- **`lib/useApi.ts`** — `useApi(fn, deps)` runs an async fetch, exposing
  `{ data, loading, error, reload }`.
- **`store/user.ts`** — Zustand store `{ userId, setUserId }`, persisted to
  `localStorage` (default `"demo-user"`).

### Pages

- **Feed (`/`)** — reads `userId`; calls `getFeed`. Header `SearchBar`: when a
  query is present, the list shows `search` results instead of the feed
  (`FeedList` vs results view toggled by query state). Each `ArticleCard` links to
  `/articles/[id]` and shows `SignalBadge`s. Loading spinner, error with retry,
  empty state ("No articles yet — set your preferences").
- **Article detail (`/articles/[id]`)** — `getArticle`; renders title, summary,
  description, detected suppliers/regions/categories, signals, source link
  (external), processed metadata. 404 → "Article not found" state.
- **Preferences (`/preferences`)** — `getPreferences` to prefill; `PreferenceForm`
  edits four interested lists + four excluded lists as add/remove tag inputs;
  `savePreferences` on submit with success/error feedback. Missing preferences
  (404) start from empty lists.
- **Chat (`/chat`)** — `ConversationList` (from `listConversations`) + "New
  conversation" (`createConversation`). Selecting a conversation loads history
  (`getMessages`) and opens the WebSocket. `ChatWindow` sends `{ message }`,
  renders messages, and streams the assistant reply via `chatReducer`. Connection
  status indicator; on close, allow reconnect.

## Data Flow

1. `Header` lets the user view/edit `userId` (persisted). Changing it triggers
   dependent pages to refetch (via `useApi` deps).
2. Feed/Article/Preferences: client component → `useApi(() => api.x(...))` →
   render states.
3. Chat: choose/create conversation → `getMessages` → `openChatSocket` → on send,
   frames flow through `chatReducer` into rendered messages; server persists both
   sides (SP-1), so a later `getMessages` reflects the exchange.

## Error Handling & States

- API errors: `useApi` captures them; views render an inline error + "Retry".
- Empty results: dedicated empty states (feed, search, conversations).
- WebSocket: `onError`/`onClose` surface a status; a "Reconnect" affordance
  reopens the socket. `error` frames render as an assistant-side error notice
  without breaking the thread.

## Testing Strategy (definition of done)

- **Vitest + RTL (jsdom):**
  - `lib/api`: functions call the right paths/params and return typed data (Axios mocked).
  - `lib/chatReducer`: start/stream/end/error folding, multi-delta accumulation.
  - `store/user`: default value + persistence + update.
  - `components`: `SignalBadge` (priority styling), `ArticleCard` (renders title/
    signals, links), `PreferenceForm` (add/remove tag, submit calls save),
    Feed page search/feed toggle (mocked `api`).
- **Gates:** `tsc --noEmit`, `next lint`, `next build` all succeed.
- Backend is mocked; no live server required (true integration is SP-3).

## File-Level Change Summary

All new under `frontend/`. No backend files change in SP-2. SP-3 will add the
frontend service to `docker-compose.yml` and a root run-doc update.

## Open Decisions (resolved)

- **Search location:** folded into the Feed page (keeps the PRD's four pages).
- **Components:** hand-rolled Tailwind, no shadcn CLI.
- **Testing bar:** Vitest/RTL + typecheck + lint + build.
- **Identity:** persisted `user_id` string, editable in the header (no auth).
