# SP-3 Design — Full-Stack Integration & Verification

**Date:** 2026-06-21
**Status:** Approved (design)
**Part of:** ProcureSignal Phase-1 MVP completion (SP-3 of 3 — final)

## Context

SP-1 delivered the backend (chat subsystem + hardening); SP-2 delivered the
Next.js frontend. SP-3 wires the frontend into `docker-compose`, fills the gaps
that prevent a fresh stack from working end-to-end, and adds an automated
structural smoke test plus run docs. This is the integration layer — it touches
infra (`docker-compose.yml`, `README.md`, new Docker/scripts files) and adds no
application logic.

### Current deployment state (from the repo)

`docker-compose.yml` runs: postgres (5433→5432), redis (6379), api (8000,
`--reload`, mounts `./api`+`./shared`), worker, beat, flower (5555), grafana
(3000), prometheus (9090). Gaps that block a working full stack:

1. **No frontend service** and **no `frontend/Dockerfile`**.
2. **Port clash:** Grafana publishes `3000`, which the frontend needs.
3. **No migration step:** nothing runs `alembic upgrade head`, so a fresh DB has
   no schema and the API errors on first query. (`alembic.ini` + `migrations/`
   exist; current head `a1b2c3_add_chat_tables`.)
4. **No external secrets wired:** `GROQ_API_KEY` / `NEWSAPI_KEY` are not passed
   to api/worker, so enrichment and retrieval can't run.
5. **No data bootstrap:** beat's retrieval cron is every 6h, so a fresh stack
   shows empty feeds for a long time.

Worker task names (for the bootstrap): `worker.tasks.retrieve_news_task`,
`normalize_articles_task`, `enrich_articles_task`, `personalize_feeds_task`.

Docker (29.5.3) and docker-compose are available in the target environment, so
the stack can actually be booted and the smoke test run as the definition of done.

## Goals

- `docker compose up` brings up the **entire** stack — db, redis, migrate, api,
  worker, beat, frontend, and supporting tools — with correct ordering.
- The frontend (production build) is reachable at `http://localhost:3000` and
  talks to the API at `http://localhost:8000`.
- The retrieval → enrichment → personalization pipeline runs once on startup to
  populate real demo data (best-effort; requires keys).
- An automated structural smoke test verifies every API/WS contract end-to-end
  and exits non-zero on any violation.
- README documents env setup, launch, port map, and how to run the smoke test.

## Non-Goals (YAGNI)

- Production hardening (TLS, nginx, secrets vaults, k8s) — TRD lists these as
  later stages.
- Changing any application logic in `api/`, `shared/`, `worker/`, or `frontend/`
  source (beyond the new Dockerfile/compose/scripts/docs).
- Load/E2E browser tests (Playwright) — the smoke test is API/WS-level.

## Design

### 1. Frontend Docker image — `frontend/Dockerfile`

Multi-stage:
- **builder** (`node:20-alpine`): `npm ci`, then `next build`. `NEXT_PUBLIC_API_URL`
  and `NEXT_PUBLIC_WS_URL` are declared as `ARG`s and exported to `ENV` before
  `next build`, because Next.js inlines `NEXT_PUBLIC_*` at build time. Defaults:
  `http://localhost:8000` and `ws://localhost:8000`.
- **runtime** (`node:20-alpine`): copies the build output and `node_modules`,
  runs `next start -p 3000`. Exposes `3000`.

A `frontend/.dockerignore` excludes `node_modules`, `.next`, `.env.local`.

### 2. docker-compose changes

- **Add `frontend` service:** builds `frontend/Dockerfile` with the two
  `NEXT_PUBLIC_*` build args, `ports: 3000:3000`, `depends_on: api:
  service_healthy`.
- **Move Grafana** to `3001:3000` (frontend owns host `3000`).
- **Add `migrate` one-shot service:** uses the api image, mounts `./migrations`
  and `./alembic.ini` (plus `./shared`), command `alembic upgrade head`, same
  `DATABASE_URL`, `depends_on: postgres: service_healthy`. `api`, `worker`,
  `beat` add `depends_on: migrate: service_completed_successfully`.
- **Wire secrets:** add `GROQ_API_KEY: ${GROQ_API_KEY:-}` and `NEWSAPI_KEY:
  ${NEWSAPI_KEY:-}` to `api`, `worker`, `beat`, `bootstrap`. Compose auto-reads a
  gitignored root `.env`. A committed `.env.example` documents all variables.
- **Add `bootstrap` one-shot service:** uses the worker image, `depends_on:
  migrate: completed` + `worker: started`, runs a small Python entrypoint that
  enqueues the pipeline once (retrieve → normalize → enrich → personalize) via
  Celery `send_task` with short staggered countdowns, then exits 0. Tolerant of
  missing keys / empty results (logs a warning, never fails the stack).

### 3. Smoke test — `scripts/smoke_test.py`

A standalone script (httpx + `websockets`), `API_URL`/`WS_URL` from env
(defaults `http://localhost:8000` / `ws://localhost:8000`), run after the stack
is up:

1. Poll `GET /health` until healthy or timeout (~60s).
2. `GET /` → service banner; `GET /api/health` → `database: connected`.
3. `POST /api/preferences` (demo user, sample lists) then `GET /api/preferences`
   → values round-trip.
4. `GET /api/feed?user_id=demo-user` → valid `FeedResponse` shape, `total_count
   >= 0` (tolerant of async retrieval; does not require populated data).
5. `GET /api/search?q=tariff` → valid `SearchResponse` shape.
6. `POST /api/conversations?user_id=demo-user` → `conversation_id`; `GET
   /api/conversations` includes it; `GET /api/conversations/{id}/messages` →
   empty list.
7. **WS** `/api/ws/chat/demo-user/{id}`: send `{"message": "..."}`; assert the
   first frame is `type=="start"`, then read frames until `end` **or** `error`
   (both protocol-valid — content is not asserted, so the test is deterministic
   regardless of whether Groq responds). A frame with an unknown `type` or a
   missing `start` fails the test.

Prints a per-check ✓/✗ summary and exits non-zero on the first contract
violation. Has a `--wait` mode that polls health before running (for use right
after `docker compose up`).

### 4. Run docs — `README.md`

Update the Quick Start: copy `.env.example` → `.env` and fill `GROQ_API_KEY` /
`NEWSAPI_KEY`; `docker compose up -d --build`; wait for health; the port map
(**frontend 3000**, API 8000, Grafana **3001**, Flower 5555, Prometheus 9090,
Postgres 5433, Redis 6379); and `python scripts/smoke_test.py --wait` to verify.

### 5. Error handling & ordering

- `service_healthy` (postgres/redis/api) and `service_completed_successfully`
  (migrate) gate startup so the schema and deps exist before dependents run.
- `bootstrap` is best-effort: pipeline/keys failures log and exit 0 — they never
  block the stack or the smoke test.
- The smoke test polls health with a timeout and fails fast with a clear message
  if the stack isn't reachable.

## Testing Strategy (definition of done)

- `docker compose config` validates (no YAML/ref errors).
- `docker compose up -d --build` brings the full stack to healthy.
- `python scripts/smoke_test.py --wait` passes (all contract checks ✓).
- The frontend loads at `http://localhost:3000` (HTTP 200 on `/`).
- Existing backend + frontend unit/integration suites remain green (unchanged).

## File-Level Change Summary

New:
- `frontend/Dockerfile`, `frontend/.dockerignore`
- `scripts/smoke_test.py`
- `scripts/bootstrap_pipeline.py` (the `bootstrap` service entrypoint)
- `.env.example` (root)

Modified:
- `docker-compose.yml` (frontend, migrate, bootstrap services; grafana port;
  secrets passthrough; depends_on ordering)
- `README.md` (run docs / port map / smoke test)
- `.gitignore` (ensure root `.env` ignored — verify; `.env.local` already covered)

No application source changes in `api/`, `shared/`, `worker/`, `frontend/src`.
