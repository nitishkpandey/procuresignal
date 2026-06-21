# Full-Stack Integration & Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Next.js frontend into `docker-compose`, add the missing migration/secrets/data-bootstrap steps, and add an automated structural smoke test + run docs, so `docker compose up` brings the whole ProcureSignal stack up and a single script verifies every API/WS contract end-to-end.

**Architecture:** A multi-stage `frontend/Dockerfile` (production `next build`/`next start`). `docker-compose.yml` gains a `frontend` service (host 3000), a one-shot `migrate` service (`alembic upgrade head`) that gates api/worker/beat, secrets passthrough from a gitignored `.env`, and a one-shot `bootstrap` service that enqueues the retrieval pipeline once. Grafana moves off 3000 → 3001. A standalone `scripts/smoke_test.py` exercises REST + WebSocket contracts against the running stack.

**Tech Stack:** Docker / docker-compose, Next.js 14 (node:20-alpine), Python 3.11 (httpx + websockets for the smoke test, Celery for the bootstrap), Alembic, Postgres, Redis.

## Global Constraints

- No application source changes in `api/`, `shared/`, `worker/`, or `frontend/` app code. SP-3 only adds/edits infra: `frontend/Dockerfile`, `frontend/.dockerignore`, `docker-compose.yml`, `.env.example`, `scripts/*.py`, `README.md`, and a smoke-test unit test under `tests/`.
- Ports (host): **frontend 3000**, API 8000, **Grafana 3001**, Flower 5555, Prometheus 9090, Postgres 5433, Redis 6379.
- `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` are browser-facing and must point at the host-published API: `http://localhost:8000` / `ws://localhost:8000`. They are baked at `next build` time (Next inlines `NEXT_PUBLIC_*`).
- Secrets (`GROQ_API_KEY`, `NEWSAPI_KEY`) come from a gitignored root `.env` (compose auto-reads it); `.env.example` documents them. `.env` is already in `.gitignore`.
- The `bootstrap` service is best-effort: it never fails the stack. The smoke test is tolerant of async retrieval (does not require populated data) and asserts the WS frame *protocol*, not LLM content.
- Worker task names: `worker.tasks.retrieve_news_task` (queue `retrieval`), `worker.tasks.normalize_articles_task` (queue `processing`), `worker.tasks.enrich_articles_task` (queue `enrichment`), `worker.tasks.personalize_feeds_task` (queue `personalization`).
- Current Alembic head: `a1b2c3_add_chat_tables`. The api image (`Dockerfile.api`) does NOT contain `migrations/` or `alembic.ini`, so the migrate service must mount them.
- Backend runs on branch with SP-1 + SP-2 merged (this branch `phase/11-integration` is stacked on `phase/10-frontend`).

---

### Task 1: Frontend production Docker image + env example

**Files:**
- Create: `frontend/Dockerfile`, `frontend/.dockerignore`
- Modify: `.env.example` (root)

**Interfaces:**
- Produces: a buildable frontend image that serves `next start` on port 3000, parameterized by `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` build args.

- [ ] **Step 1: Create `frontend/.dockerignore`**

```
node_modules
.next
out
coverage
.env.local
npm-debug.log*
```

- [ ] **Step 2: Create `frontend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1

# ---- builder ----
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---- runner ----
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000
CMD ["npm", "run", "start"]
```

Note: do NOT copy a `public/` directory — the frontend has none, and `COPY public` would fail the build.

- [ ] **Step 3: Add the frontend env vars to `.env.example`**

Append to the existing `.env.example` (keep all existing lines):

```
# Frontend (browser-facing; point at the host-published API)
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

- [ ] **Step 4: Build the image to verify it succeeds**

Run:
```bash
cd frontend && docker build -t procuresignal-frontend:test .
```
Expected: build completes through both stages, ending with an image tagged `procuresignal-frontend:test`. (The `next build` step prints the 4 routes `/`, `/articles/[id]`, `/preferences`, `/chat`.)

- [ ] **Step 5: Smoke-run the image briefly**

Run:
```bash
docker run -d --name fe-test -p 3100:3000 procuresignal-frontend:test
sleep 4 && curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:3100/ ; docker rm -f fe-test
```
Expected: prints `200`.

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/.dockerignore .env.example
git commit -m "feat(integration): add production frontend Dockerfile and env example"
```

---

### Task 2: docker-compose — frontend, migrate, ordering, secrets, grafana port

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `frontend/Dockerfile` (Task 1).
- Produces: `frontend` service (host 3000), `migrate` one-shot service, secrets wired to api/worker/beat, grafana on 3001. `bootstrap` is added in Task 3.

- [ ] **Step 1: Add a `migrate` one-shot service**

Insert this service (e.g. right after the `redis` service) in `docker-compose.yml`:

```yaml
  migrate:
    build:
      context: .
      dockerfile: Dockerfile.api
    container_name: procuresignal-migrate
    environment:
      DATABASE_URL: postgresql+asyncpg://procuresignal:procuresignal@postgres:5432/procuresignal
      LOG_LEVEL: INFO
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./shared:/app/shared
      - ./migrations:/app/migrations
      - ./alembic.ini:/app/alembic.ini
    command: alembic upgrade head
    restart: "no"
```

- [ ] **Step 2: Gate api/worker/beat on migrate + add secrets**

In the `api` service: add `migrate` to `depends_on` and the two secrets to `environment`:

```yaml
    environment:
      DATABASE_URL: postgresql+asyncpg://procuresignal:procuresignal@postgres:5432/procuresignal
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/1
      LOG_LEVEL: INFO
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      NEWSAPI_KEY: ${NEWSAPI_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
```

In the `worker` service: add the same two secrets to `environment` and add the `migrate` dependency to its existing `depends_on`:

```yaml
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      NEWSAPI_KEY: ${NEWSAPI_KEY:-}
```
```yaml
      migrate:
        condition: service_completed_successfully
```

In the `beat` service: add the `migrate` dependency to its existing `depends_on`:

```yaml
      migrate:
        condition: service_completed_successfully
```

- [ ] **Step 3: Move Grafana off port 3000**

In the `grafana` service, change the published port:

```yaml
    ports:
      - "3001:3000"
```

- [ ] **Step 4: Add the `frontend` service**

Add this service (e.g. after `api`):

```yaml
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        NEXT_PUBLIC_API_URL: http://localhost:8000
        NEXT_PUBLIC_WS_URL: ws://localhost:8000
    container_name: procuresignal-frontend
    ports:
      - "3000:3000"
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 5: Validate the compose file**

Run:
```bash
docker compose config >/dev/null && echo "compose config OK"
```
Expected: prints `compose config OK` (no YAML or reference errors).

- [ ] **Step 6: Assert the key wiring with grep**

Run:
```bash
docker compose config | grep -E "procuresignal-frontend|3001|condition: service_completed_successfully" | head
```
Expected: shows the frontend container, the `3001` grafana mapping, and at least one `service_completed_successfully` (migrate gating).

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(integration): add frontend + migrate services, wire secrets, move grafana to 3001"
```

---

### Task 3: Data bootstrap (one-shot pipeline trigger)

**Files:**
- Create: `scripts/bootstrap_pipeline.py`
- Modify: `docker-compose.yml` (add `bootstrap` service)

**Interfaces:**
- Consumes: the `migrate` + `worker` services (Task 2), worker task names (global constraints).
- Produces: `scripts/bootstrap_pipeline.py` with `main() -> int`; a `bootstrap` compose service that runs it once.

- [ ] **Step 1: Create `scripts/bootstrap_pipeline.py`**

```python
"""One-shot: enqueue the retrieval -> normalize -> enrich -> personalize pipeline.

Run as the docker-compose `bootstrap` service so a fresh stack populates real
demo data. Best-effort: logs and returns 0 even if the broker is unreachable or
keys are missing, so it never blocks the stack.
"""

import os
import sys

from celery import Celery

BROKER = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

# (task name, queue, countdown seconds) — staggered so each stage runs after the
# previous has had time to produce rows.
PIPELINE = [
    ("worker.tasks.retrieve_news_task", "retrieval", 0),
    ("worker.tasks.normalize_articles_task", "processing", 60),
    ("worker.tasks.enrich_articles_task", "enrichment", 120),
    ("worker.tasks.personalize_feeds_task", "personalization", 180),
]


def main() -> int:
    try:
        app = Celery(broker=BROKER, backend=BACKEND)
        for name, queue, countdown in PIPELINE:
            app.send_task(name, queue=queue, countdown=countdown)
            print(f"[bootstrap] enqueued {name} (queue={queue}, countdown={countdown}s)")
        print("[bootstrap] pipeline enqueued; data populates as workers process tasks.")
    except Exception as exc:  # noqa: BLE001 - best-effort, must never block the stack
        print(f"[bootstrap] WARNING: could not enqueue pipeline: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add the `bootstrap` service to `docker-compose.yml`**

```yaml
  bootstrap:
    build:
      context: .
      dockerfile: Dockerfile.worker
    container_name: procuresignal-bootstrap
    environment:
      CELERY_BROKER_URL: redis://redis:6379/1
      CELERY_RESULT_BACKEND: redis://redis:6379/2
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      NEWSAPI_KEY: ${NEWSAPI_KEY:-}
    depends_on:
      redis:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
      worker:
        condition: service_started
    volumes:
      - ./scripts:/app/scripts
      - ./shared:/app/shared
      - ./worker:/app/worker
    command: python /app/scripts/bootstrap_pipeline.py
    restart: "no"
```

- [ ] **Step 3: Verify the script imports and compose still validates**

Run:
```bash
.venv/bin/python -c "import ast; ast.parse(open('scripts/bootstrap_pipeline.py').read()); print('parse OK')"
docker compose config >/dev/null && echo "compose config OK"
```
Expected: `parse OK` then `compose config OK`.

- [ ] **Step 4: Commit**

```bash
git add scripts/bootstrap_pipeline.py docker-compose.yml
git commit -m "feat(integration): add one-shot pipeline bootstrap service"
```

---

### Task 4: Structural smoke test

**Files:**
- Create: `scripts/smoke_test.py`
- Test: `tests/integration/test_smoke_helpers.py`

**Interfaces:**
- Produces: `scripts/smoke_test.py` runnable as `python scripts/smoke_test.py [--wait]`, reading `API_URL` / `WS_URL` from env (defaults `http://localhost:8000` / `ws://localhost:8000`). Pure helper `assert_valid_frame_sequence(frames: list[dict]) -> None` raises `AssertionError` on an invalid frame sequence.

- [ ] **Step 1: Write the failing unit test for the frame validator**

`tests/integration/test_smoke_helpers.py`:
```python
"""Unit tests for the smoke test's pure WS-frame validator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from smoke_test import assert_valid_frame_sequence  # noqa: E402


def test_valid_stream_sequence():
    frames = [
        {"type": "start", "content": ""},
        {"type": "stream", "content": "Hi"},
        {"type": "end", "content": "done"},
    ]
    assert_valid_frame_sequence(frames)  # should not raise


def test_valid_error_sequence():
    frames = [
        {"type": "start", "content": ""},
        {"type": "error", "content": "boom"},
    ]
    assert_valid_frame_sequence(frames)  # start then clean error is valid


def test_missing_start_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence([{"type": "stream", "content": "x"}])


def test_unknown_type_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence(
            [{"type": "start", "content": ""}, {"type": "bogus", "content": "x"}]
        )


def test_unterminated_raises():
    with pytest.raises(AssertionError):
        assert_valid_frame_sequence(
            [{"type": "start", "content": ""}, {"type": "stream", "content": "x"}]
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_smoke_helpers.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'smoke_test'`.

- [ ] **Step 3: Create `scripts/smoke_test.py`**

```python
"""Structural full-stack smoke test for ProcureSignal.

Runs against a live stack (default http://localhost:8000). Verifies REST and
WebSocket contracts and exits non-zero on the first violation. Tolerant of async
retrieval: it does not require the feed to be populated, and it asserts the WS
frame *protocol*, not LLM content.

Requires: httpx, websockets  (pip install httpx websockets)
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx

VALID_TERMINAL = {"end", "error"}
VALID_TYPES = {"start", "stream", "end", "error"}


def assert_valid_frame_sequence(frames: list[dict]) -> None:
    """Raise AssertionError unless frames form a valid chat-WS sequence."""
    assert frames, "no frames received"
    assert frames[0].get("type") == "start", f"first frame must be 'start', got {frames[0]!r}"
    for f in frames:
        assert f.get("type") in VALID_TYPES, f"unknown frame type: {f!r}"
    assert frames[-1].get("type") in VALID_TERMINAL, (
        f"sequence must end with 'end' or 'error', got {frames[-1]!r}"
    )


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + (f" - {detail}" if detail and not ok else ""))
        if not ok:
            self.failures += 1


def wait_for_health(base: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2.0)
    return False


async def collect_ws_frames(ws_url: str, user_id: str, conversation_id: str) -> list[dict]:
    import websockets  # lazy import so the validator is unit-testable without the dep

    url = f"{ws_url}/api/ws/chat/{user_id}/{conversation_id}"
    frames: list[dict] = []
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"message": "What does a tariff mean for my supply chain?"}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
            frame = json.loads(raw)
            frames.append(frame)
            if frame.get("type") in VALID_TERMINAL:
                break
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="ProcureSignal full-stack smoke test")
    parser.add_argument("--wait", action="store_true", help="poll /health before running")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8000"))
    parser.add_argument("--ws-url", default=os.getenv("WS_URL", "ws://localhost:8000"))
    args = parser.parse_args()

    api = args.api_url.rstrip("/")
    c = Checker()
    user_id = "demo-user"

    if args.wait:
        print(f"Waiting for {api}/health ...")
        if not wait_for_health(api):
            print("✗ API never became healthy", file=sys.stderr)
            return 1

    print("REST checks:")
    r = httpx.get(f"{api}/health", timeout=5.0)
    c.check("GET /health", r.status_code == 200 and r.json().get("status") == "healthy")

    r = httpx.get(f"{api}/api/health", timeout=5.0)
    c.check("GET /api/health database connected", r.status_code == 200 and r.json().get("database") == "connected")

    prefs = {
        "user_id": user_id,
        "interested_categories": ["automotive"],
        "interested_suppliers": ["Bosch"],
        "interested_regions": ["Germany"],
        "interested_signals": ["tariff"],
        "excluded_categories": [],
        "excluded_suppliers": [],
        "excluded_regions": [],
        "excluded_signals": [],
    }
    r = httpx.post(f"{api}/api/preferences", json=prefs, timeout=10.0)
    c.check("POST /api/preferences", r.status_code == 200)
    r = httpx.get(f"{api}/api/preferences", params={"user_id": user_id}, timeout=10.0)
    c.check(
        "GET /api/preferences round-trips",
        r.status_code == 200 and "bosch" in [s.lower() for s in r.json().get("interested_suppliers", [])],
    )

    r = httpx.get(f"{api}/api/feed", params={"user_id": user_id, "limit": 10}, timeout=20.0)
    body = r.json() if r.status_code == 200 else {}
    c.check(
        "GET /api/feed valid shape",
        r.status_code == 200 and isinstance(body.get("articles"), list) and body.get("total_count", -1) >= 0,
    )

    r = httpx.get(f"{api}/api/search", params={"q": "tariff", "limit": 5}, timeout=10.0)
    body = r.json() if r.status_code == 200 else {}
    c.check(
        "GET /api/search valid shape",
        r.status_code == 200 and isinstance(body.get("results"), list) and body.get("query") == "tariff",
    )

    r = httpx.post(f"{api}/api/conversations", params={"user_id": user_id}, timeout=10.0)
    conv_id = r.json().get("conversation_id") if r.status_code == 200 else None
    c.check("POST /api/conversations", bool(conv_id))

    r = httpx.get(f"{api}/api/conversations", params={"user_id": user_id}, timeout=10.0)
    ids = [conv.get("conversation_id") for conv in r.json().get("conversations", [])] if r.status_code == 200 else []
    c.check("GET /api/conversations lists new id", conv_id in ids)

    if conv_id:
        r = httpx.get(f"{api}/api/conversations/{conv_id}/messages", timeout=10.0)
        c.check("GET messages (empty)", r.status_code == 200 and r.json().get("total_count") == 0)

    print("WebSocket check:")
    ws_conv = conv_id or str(uuid.uuid4())
    try:
        frames = asyncio.run(collect_ws_frames(args.ws_url.rstrip("/"), user_id, ws_conv))
        assert_valid_frame_sequence(frames)
        c.check(f"WS chat protocol ({len(frames)} frames, ends {frames[-1]['type']})", True)
    except Exception as exc:  # noqa: BLE001
        c.check("WS chat protocol", False, str(exc))

    print()
    if c.failures:
        print(f"SMOKE TEST FAILED: {c.failures} check(s) failed.")
        return 1
    print("SMOKE TEST PASSED: all checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_smoke_helpers.py -q --no-cov`
Expected: 5 passed.

- [ ] **Step 5: Confirm the script imports cleanly (and CLI parses)**

Run: `.venv/bin/python scripts/smoke_test.py --help`
Expected: prints usage with `--wait`, `--api-url`, `--ws-url` (no import error; `httpx` is already installed in the venv).

- [ ] **Step 6: Commit**

```bash
git add scripts/smoke_test.py tests/integration/test_smoke_helpers.py
git commit -m "feat(integration): add structural full-stack smoke test"
```

---

### Task 5: Run documentation

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Replace the README "Running Locally" / Quick Start section**

Find the existing Quick Start fenced block in `README.md` (the `docker-compose up -d` instructions near the top) and replace that section's body with:

````markdown
### Running Locally (full stack)

```bash
# 1. Configure secrets
cp .env.example .env
#   edit .env and set GROQ_API_KEY and NEWSAPI_KEY

# 2. Build and start the whole stack
docker compose up -d --build

# 3. Wait for the API to be healthy, then verify end-to-end
pip install httpx websockets   # one-time, for the smoke test
python scripts/smoke_test.py --wait
```

### Service URLs / ports

| Service     | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3000        |
| API + docs  | http://localhost:8000/docs   |
| Grafana     | http://localhost:3001 (admin/admin) |
| Flower      | http://localhost:5555        |
| Prometheus  | http://localhost:9090        |
| Postgres    | localhost:5433               |
| Redis       | localhost:6379               |

Migrations run automatically (the `migrate` service runs `alembic upgrade head`
before the API starts). The one-shot `bootstrap` service triggers the
retrieval → enrichment → personalization pipeline once so the feed populates
with real articles over the following minutes (requires `NEWSAPI_KEY` /
`GROQ_API_KEY`).
````

- [ ] **Step 2: Verify the doc references are consistent**

Run:
```bash
grep -E "localhost:3000|localhost:3001|smoke_test.py" README.md | head
```
Expected: shows the frontend on 3000, Grafana on 3001, and the smoke-test command.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(integration): document full-stack run + smoke test + port map"
```

---

### Task 6: Full-stack verification (definition of done)

**Files:** none (verification only). Requires Docker running and a `.env` with valid `GROQ_API_KEY` / `NEWSAPI_KEY`.

- [ ] **Step 1: Prepare env**

```bash
cp -n .env.example .env || true
# ensure GROQ_API_KEY and NEWSAPI_KEY are set in .env (non-empty)
grep -E "GROQ_API_KEY=.+|NEWSAPI_KEY=.+" .env && echo "keys present"
```
Expected: `keys present` (if not, fill them before continuing).

- [ ] **Step 2: Validate compose then build + start the stack**

```bash
docker compose config >/dev/null && echo "config OK"
docker compose up -d --build
```
Expected: `config OK`, then all services start. `migrate` runs to completion (exit 0) before `api` starts.

- [ ] **Step 3: Confirm migrate created the schema**

```bash
docker compose exec -T postgres psql -U procuresignal -d procuresignal -c "\dt" | grep -E "news_articles_raw|chat_conversations" | head
```
Expected: the core tables (incl. `chat_conversations`) exist. If `migrate` failed, inspect `docker compose logs migrate` — a clean re-run is `docker compose run --rm migrate`.

- [ ] **Step 4: Run the smoke test**

```bash
.venv/bin/python -m pip install -q httpx websockets
.venv/bin/python scripts/smoke_test.py --wait
```
Expected: every check prints `✓` and the script prints `SMOKE TEST PASSED` and exits 0.

- [ ] **Step 5: Confirm the frontend serves and the full unit suites are green**

```bash
curl -sf -o /dev/null -w "frontend: %{http_code}\n" http://localhost:3000/
.venv/bin/python -m pytest -q 2>&1 | tail -3
cd frontend && npm run test:run 2>&1 | tail -3
```
Expected: `frontend: 200`; backend suite passes (76 tests — 71 existing + 5 new smoke-helper tests); frontend suite passes (24 tests).

- [ ] **Step 6: Tear down (optional) and commit any fixups**

```bash
docker compose down
git add -A && git commit -m "chore(integration): verification fixups" || echo "nothing to commit"
```

---

## Definition of Done (SP-3)

- `docker compose up -d --build` brings up the full stack (db, redis, migrate, api, worker, beat, bootstrap, frontend, flower, grafana, prometheus) with correct ordering.
- `migrate` applies `alembic upgrade head` before the API starts; the schema exists.
- Frontend is reachable at `http://localhost:3000`; Grafana moved to `3001` (no port clash).
- `GROQ_API_KEY` / `NEWSAPI_KEY` flow from `.env`; `bootstrap` triggers the pipeline once (best-effort).
- `python scripts/smoke_test.py --wait` passes all REST + WS contract checks; the frame-validator unit test is green.
- README documents env, launch, port map, and the smoke test.
- No application source changed; backend (76: 71 existing + 5 smoke-helper) and frontend (24) suites stay green.
