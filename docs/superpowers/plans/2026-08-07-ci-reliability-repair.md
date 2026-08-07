# CI Reliability Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local and GitHub verification boundaries deterministic while retaining real
coverage of Redis sharing, frontend asynchronous states, route contracts, and concurrent leases.

**Architecture:** Ordinary API tests use the in-process rate limiter so every test owns its state;
a dedicated integration test exercises two real Redis clients against the CI service and cleans up
its unique keys. Frontend tests synchronize on user-visible completed states. SQLite concurrency
tests use WAL and an explicit busy timeout so transient writer contention is waited out rather than
randomly failing.

**Tech Stack:** GitHub Actions, pytest, redis-py asyncio, FastAPI, SQLAlchemy/aiosqlite, Vitest,
Testing Library, Next.js 16.

## Global Constraints

- Do not remove Redis from CI; prove the shared backend through a dedicated integration test.
- Do not weaken assertions, add arbitrary sleeps, or retry the whole test suite.
- Keep the webpack route-contract gate and both Docker image checks blocking.
- Run the exact CI commands locally before pushing.
- Commit the CI repair separately from Phase 4 feature work.

---

### Task 1: Isolate ordinary tests and retain real Redis coverage

**Files:**
- Create: `tests/integration/test_redis_backend.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `api/rate_limit.py`
- Test: `tests/unit/test_redis_rate_limit.py`

**Interfaces:**
- Consumes: `RedisWindow`, `REDIS_URL`, the GitHub Redis service.
- Produces: `close_backend() -> None` and a separately executed real-Redis integration test.

- [x] **Step 1: Add a failing backend-lifecycle test**

Add a fake async client with an `aclose` spy and assert `close_backend(client)` closes it. Run the
single test and verify the helper is missing.

- [x] **Step 2: Implement lifecycle cleanup**

Add `close_backend(client: Any | None = None) -> None`; close the configured client when present,
and invoke it from the API lifespan shutdown path.

- [x] **Step 3: Add real Redis integration coverage**

Use two separately created Redis clients and one UUID-suffixed key. Record across both windows,
assert the combined limit is enforced, delete the key, and close both clients in `finally`.

- [x] **Step 4: Split CI environments**

Run the main pytest command without `REDIS_URL`, then run only
`tests/integration/test_redis_backend.py` with `REDIS_URL=redis://localhost:6379/0` in a fresh
process. This prevents unrelated tests from sharing the registration bucket while retaining a
real broker contract.

- [x] **Step 5: Verify backend tests**

Run the rate-limit unit tests, authentication/tenant integration tests, and the real Redis test.

### Task 2: Remove frontend timing races

**Files:**
- Modify: `frontend/__tests__/chat-view.test.tsx`
- Modify: `frontend/__tests__/currency-view.test.tsx`
- Inspect and modify only where the same defect exists: `frontend/__tests__/*.test.tsx`

**Interfaces:**
- Consumes: Testing Library asynchronous queries.
- Produces: tests synchronized on completed user-visible states.

- [x] **Step 1: Preserve the two observed failing cases**

Use the GitHub failures as the red evidence: the chat test observed its loading spinner and the
currency test observed its loading spinner before asserting loaded content.

- [x] **Step 2: Await completed states**

Replace waits on headings or mock calls that are already true during loading with `findBy*` or
`waitForElementToBeRemoved` against the final user-visible result.

- [x] **Step 3: Audit the remaining frontend suite for the same pattern**

Change only tests that await an element present in the initial loading render and immediately make
synchronous assertions about fetched data.

- [ ] **Step 4: Verify repeatedly**

Run the full 72-test suite multiple times, then typecheck, lint, the production build, and the
webpack route-contract build.

### Task 3: Make the SQLite lease test deterministic

**Files:**
- Modify: `tests/unit/test_retrieval_orchestrator.py`

**Interfaces:**
- Consumes: the file-backed SQLite fixture used only by retrieval-orchestrator tests.
- Produces: a fixture that waits for transient writer locks while preserving concurrent claims.

- [x] **Step 1: Retain the observed failure as red evidence**

The GitHub run failed in `claim_run` with `sqlite3.OperationalError: database is locked` during two
concurrent claims; the following run passed unchanged, proving nondeterminism.

- [x] **Step 2: Configure the test database for legitimate concurrency**

Set SQLite's connection timeout and `PRAGMA journal_mode=WAL`/`busy_timeout` in the fixture. Do not
catch the exception in production or weaken the lease assertions.

- [x] **Step 3: Verify repeatedly**

Run the concurrency test repeatedly and then the complete retrieval-orchestrator module.

### Task 4: Run the production gate and publish the repair

**Files:**
- Verify: the complete repository.

**Interfaces:**
- Consumes: every command in `.github/workflows/ci.yml`.
- Produces: one focused human-readable commit on `main` and a completed GitHub Actions run.

- [x] **Step 1: Run all backend gates**

Run pytest with coverage, Ruff, Black, MyPy, dependency audit, and migration checks.

- [ ] **Step 2: Run all frontend gates**

Run tests, typecheck, lint, Turbopack production build, and webpack route-contract build.

- [x] **Step 3: Run deployable-artifact gates**

Build and smoke-test the API and worker images using the same commands as CI.

If an architecture-specific dependency has no wheel, the image must include the complete native
build toolchain rather than passing only on GitHub's x86 runner. The Docker Poetry version must
match CI, and the production API command must not enable source-code reload.

- [ ] **Step 4: Commit and push**

Commit only the reviewed repair files with a human-readable message and push `main`.

- [ ] **Step 5: Observe GitHub Actions**

Wait for the pushed run to finish. Do not report green while it is queued or in progress.

### Task 5: Begin the next canonical phase

**Files:**
- Inspect: the running application and Phase 4 dependencies.
- Create: a focused Phase 4 design/plan only after the browser baseline is known.

**Interfaces:**
- Consumes: the canonical roadmap's delivery order.
- Produces: a browser-verified baseline and the first independently shippable Phase 4 slice.

- [ ] **Step 1: Exercise the application in a real browser**

Start the compose stack, verify login, feed, preferences, supplier registry, currency, chat, and
risk-event routes, and record defects with screenshots or exact reproduction steps.

- [ ] **Step 2: Select the first Phase 4 slice**

Begin organization-scoped supplier watchlists, because notification rules and supplier profiles
depend on that stable membership boundary.
