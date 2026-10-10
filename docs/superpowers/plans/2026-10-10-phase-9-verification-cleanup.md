# Phase 9 Verification And Repository Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one honest end-to-end verification contract, prove the critical procurement workflow in a real browser, and leave a production-focused repository with no known dead or duplicated implementation.

**Architecture:** `scripts/verify.sh` becomes the single command contract used locally and by CI while preserving isolated CI jobs. A guarded, idempotent demo-data module gives browser tests deterministic state without adding a test endpoint or calling paid services. Evidence-producing dead-code and duplicate scanners guide a final cleanup; durable decisions move into production documentation before development-process folders are removed.

**Tech Stack:** POSIX shell, Python 3.11, pytest, Ruff, Black, MyPy, Bandit, Vulture, Node.js 24, Vitest, Playwright, Knip, JSCPD, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-10-production-completion-design.md`

## Global Constraints

- Verification discovers tests through pytest, Vitest, and Playwright; it never maintains a list of individual test files.
- Missing tools or services fail the selected group with an actionable message; no required gate silently skips or uses `|| true`.
- Browser and smoke tests use deterministic local data and never call OpenAI, NewsAPI, GDELT, RSS, sanctions, currency, or email providers.
- Demo seeding requires both an explicit environment guard and a CLI confirmation flag and accepts only `@example.test` users.
- Code or files are removed only after references, packaging, containers, CI, tests, and dynamic entry points are checked.
- Scanner exclusions name a concrete framework or generated-file reason; no blanket source-directory exclusion is allowed.
- Development-process artifacts are removed only after durable architecture, operations, demo, privacy, and open-owner decisions are preserved in production documentation.
- Every focused commit passes its relevant local group and the hosted GitHub Actions run for that exact commit.

## Review Focus

- A developer running a verification group without its service must receive a failure naming the missing precondition, not a green skip.
- Browser reload must restore identity through the HTTP-only refresh cookie over the configured local HTTP mode.
- Demo seed execution against a non-test email or without both guards must make no database changes.
- Dead-code tools must understand FastAPI, Celery, Next.js, Alembic, and CLI entry points before anything is deleted.
- CI and local verification must call the same project commands so one cannot be green while the other tests a narrower product.

---

### Task 1: Unified verification contract and CI reuse

**Files:**
- Create: `scripts/verify.sh`
- Create: `tests/unit/test_verify_script.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `CONTRIBUTING.md`
- Modify: `README.md`

**Interfaces:**
- Produces CLI: `scripts/verify.sh list`.
- Produces CLI groups: `lint`, `backend`, `frontend`, `audit`, `containers`, `system`, `quick`, and `all`.
- Consumes environment: `TEST_DATABASE_URL`, `REQUIRE_POSTGRES`, `REDIS_URL`, `AUTH_SECRET_KEY`, `VERIFY_DRY_RUN`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/unit/test_verify_script.py` using `subprocess.run`. The tests must assert:

```python
def test_list_names_every_supported_group() -> None:
    result = run_verify("list")
    assert result.returncode == 0
    assert set(result.stdout.split()) >= {
        "lint", "backend", "frontend", "audit", "containers", "system", "quick", "all"
    }


def test_unknown_group_fails_and_prints_usage() -> None:
    result = run_verify("unknown")
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_dry_run_all_contains_every_gate_once() -> None:
    result = run_verify("all", VERIFY_DRY_RUN="1")
    assert result.returncode == 0
    for fragment in (
        "generate_privacy_docs.py --check",
        "pytest tests/",
        "pytest tests/postgres",
        "test_redis_backend.py",
        "evaluate_search.py",
        "ruff check .",
        "black --check .",
        "mypy api worker shared",
        "bandit",
        "npm run test:run",
        "npm run typecheck",
        "npm run lint",
        "npm run build",
        "npm run verify:routes",
        "npm audit --audit-level=high",
        "docker build",
        "database_recovery.py drill",
        "smoke_test.py --wait",
        "npm run test:e2e",
    ):
        assert result.stdout.count(fragment) == 1


def test_backend_requires_postgres_and_redis_outside_dry_run() -> None:
    result = run_verify("backend", TEST_DATABASE_URL="", REDIS_URL="")
    assert result.returncode != 0
    assert "TEST_DATABASE_URL" in result.stderr
    assert "REDIS_URL" in result.stderr
```

`run_verify()` resolves the repository root, merges supplied variables into a minimal environment, and executes `sh scripts/verify.sh` without mocking script output.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
poetry run pytest tests/unit/test_verify_script.py -v --no-cov
```

Expected: fail because `scripts/verify.sh` does not exist.

- [ ] **Step 3: Implement strict grouped verification**

Create an executable POSIX shell script beginning:

```sh
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

run() {
  printf '+ %s\n' "$*"
  if [ "${VERIFY_DRY_RUN:-0}" != "1" ]; then
    "$@"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  }
}
```

Define one function per leaf group. Use argument-safe `run` calls, not `eval` or command strings. The groups contain these commands:

- `lint`: privacy-doc `--check`, Ruff, Black, MyPy, and Bandit over `api worker shared scripts` excluding tests.
- `backend`: full pytest with coverage floor 85, PostgreSQL suite with `REQUIRE_POSTGRES=1`, Redis integration test, and lexical search evaluation.
- `frontend`: from `frontend`, Vitest, TypeScript, ESLint, Next production build, and webpack route contract.
- `audit`: export the locked Poetry environment, run `pip-audit --strict` with the dated ignore file, then `npm audit --audit-level=high`.
- `containers`: build API, worker, and frontend images; run `uvicorn --help`, `celery --help`, and the existing frontend readiness loop.
- `system`: privacy check, recovery drill using an artifact created in a temporary directory, API/WebSocket smoke test, and Playwright.
- `quick`: `lint` plus frontend tests/typecheck/lint and backend unit/integration tests with `--no-cov` and `-m 'not postgres'`.
- `all`: each leaf group once in the order `lint backend frontend audit containers system`.

In non-dry-run mode, preflight the tools and environment only for the selected group. Use `trap` to remove temporary audit exports and backup artifacts. Preserve each child command's exit code.

- [ ] **Step 4: Verify contract tests GREEN and execute quick mode**

```bash
poetry run pytest tests/unit/test_verify_script.py -v --no-cov
scripts/verify.sh quick
```

Expected: contract tests pass and quick mode exits `0`.

- [ ] **Step 5: Replace duplicated CI command lists with verification groups**

Keep dependency installation and service declarations in GitHub Actions. Replace command bodies so jobs call:

```yaml
      - name: Verify code quality
        run: scripts/verify.sh lint
```

```yaml
      - name: Verify backend behavior
        run: scripts/verify.sh backend
```

```yaml
      - name: Verify frontend behavior
        working-directory: .
        run: scripts/verify.sh frontend
```

```yaml
      - name: Audit dependencies
        run: scripts/verify.sh audit
```

```yaml
      - name: Verify container images
        run: scripts/verify.sh containers
```

Set the test job's `TEST_DATABASE_URL`, `REQUIRE_POSTGRES=1`, and `REDIS_URL` at job scope so the shared command sees exactly the same service configuration locally and in CI. Do not make the system group part of these jobs until Task 2 supplies browser setup.

- [ ] **Step 6: Document developer usage and run leaf groups**

Update README and CONTRIBUTING with prerequisites, `quick` versus `all`, group names, required service variables, and a statement that dependency installation is deliberately outside the verifier.

Run every leaf group whose prerequisites exist locally and record any unavailable group by exact missing precondition; no unavailable group may be reported as passed.

- [ ] **Step 7: Commit, push, and confirm hosted CI**

```bash
git add scripts/verify.sh tests/unit/test_verify_script.py .github/workflows/ci.yml \
  README.md CONTRIBUTING.md
git commit -m "Make local and hosted verification use one contract"
git push origin main
```

Wait for the exact commit's CI run to succeed before Task 2.

---

### Task 2: Deterministic demo state and browser critical path

**Files:**
- Create: `shared/procuresignal/demo/__init__.py`
- Create: `shared/procuresignal/demo/seed.py`
- Create: `shared/procuresignal/demo/__main__.py`
- Create: `tests/integration/test_demo_seed.py`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/critical-path.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/verify.sh`
- Create: `docs/demo.md`

**Interfaces:**
- Produces CLI: `DEMO_SEED_ALLOWED=1 python -m procuresignal.demo --confirm-demo-data --email EMAIL`.
- Produces: `async seed_demo_state(session: AsyncSession, *, email: str) -> DemoSeedReceipt`.
- Produces npm script: `npm run test:e2e`.

- [ ] **Step 1: Write failing seed safety and idempotence tests**

Create `tests/integration/test_demo_seed.py` with a SQLite database and real ORM models. Assert:

- a missing `DEMO_SEED_ALLOWED=1` raises before opening a session;
- a missing `--confirm-demo-data` returns exit code `2`;
- an email outside `@example.test` is rejected;
- an unknown email is rejected without creating suppliers, events, notifications, or analyses;
- a known user receives one deterministic supplier, processed article/feed item, risk event, delivered notification, completed agent run, evidence step, and proposed recommendation; and
- running the seed twice returns the same public IDs and does not duplicate rows.

- [ ] **Step 2: Run seed tests and verify RED**

```bash
poetry run pytest tests/integration/test_demo_seed.py -v --no-cov
```

Expected: collection fails because `procuresignal.demo` does not exist.

- [ ] **Step 3: Implement guarded idempotent demo seeding**

Use stable keys prefixed `demo-` and query before insert. `seed_demo_state()` must resolve the existing user and membership by normalized email, then create or reuse:

- supplier `Demo Components Europe GmbH`, country `DE`, alias `Demo Components`;
- a processed article titled `Demo supplier factory disruption`, linked to a raw article whose canonical URL uses the reserved `https://example.test/` domain;
- a high-severity `supply_disruption` risk event with stable event key `demo-factory-disruption`;
- a feed row for the user;
- a delivered notification for the user through an alert rule owned by their organization; and
- a completed agent run with one verified evidence step and one proposed recommendation titled `Qualify a second source`.

Return public IDs in `DemoSeedReceipt`; never print database URLs, tokens, hashes, or internal integer IDs. The CLI checks both the environment guard and confirmation flag before constructing the engine.

- [ ] **Step 4: Verify seed tests GREEN**

```bash
poetry run pytest tests/integration/test_demo_seed.py -v --no-cov
```

Expected: all seed tests pass.

- [ ] **Step 5: Add Playwright configuration and failing browser test**

Install `@playwright/test` as a locked dev dependency and add:

```json
"test:e2e": "playwright test"
```

Configure base URL `http://127.0.0.1:3002`, one worker in CI, trace `retain-on-failure`, screenshot `only-on-failure`, and output under `frontend/test-results`.

The browser test must:

1. switch the auth gate to registration;
2. create a unique `buyer+<uuid>@example.test` owner account with a 12+ character password;
3. verify the feed shell appears;
4. invoke the guarded demo seed for that email with `execFileSync("docker", ["compose", "exec", "-T", "-e", "DEMO_SEED_ALLOWED=1", "api", "python", "-m", "procuresignal.demo", "--confirm-demo-data", "--email", email])`, never a shell string;
5. reload and verify refresh-cookie session restoration;
6. verify the seeded feed article and search result;
7. create a watchlist, find `Demo Components`, and add it;
8. open notifications and verify the seeded alert;
9. open analyses, verify evidence is visible before the decision, approve `Qualify a second source` with a note, and verify status `approved`; and
10. reload the analysis and verify the approval remains.

- [ ] **Step 6: Start the isolated stack and verify browser RED**

```bash
AUTH_SECRET_KEY=e2e-local-secret-at-least-32-characters \
AUTH_COOKIE_INSECURE=true \
CORS_ALLOWED_ORIGINS=http://127.0.0.1:3002,http://localhost:3002 \
DEMO_SEED_ALLOWED=1 \
docker compose up -d --build postgres redis migrate api worker frontend
cd frontend && npx playwright install chromium && npm run test:e2e
```

Expected: fail at the first critical-path behavior not yet supported by seed/configuration. Confirm no request reaches external providers by running with empty provider keys and reviewing container logs.

- [ ] **Step 7: Make the browser path GREEN without production test endpoints**

Expose `DEMO_SEED_ALLOWED` only to the local API container environment so `docker compose exec` can invoke the CLI. Set local CORS through the command's explicit environment as shown above; do not weaken production cookie defaults. Add stable accessible names or `data-testid` only where a role/name selector cannot uniquely identify an existing control.

Run the command in Step 6 until the critical path passes, then run it a second time from a clean volume:

```bash
docker compose down -v
```

Repeat Step 6. Expected: both a warm run and fresh-volume run pass.

- [ ] **Step 8: Add a dedicated hosted system job**

Add a CI job after build that installs locked Python/Node dependencies and Playwright Chromium, starts Compose with the exact safe E2E variables, waits on health, runs `scripts/verify.sh system`, and always uploads `frontend/test-results` plus `docker compose logs --no-color` on failure. Always run `docker compose down -v` in cleanup. Do not upload `.env`, database dumps, or cookies.

- [ ] **Step 9: Write the demo runbook**

`docs/demo.md` documents clean startup, demo seeding guard, login workflow, five-minute demo route, expected no-key degradation, reset command, and the distinction between seeded evidence and live provider data.

- [ ] **Step 10: Run full relevant gates, commit, push, and confirm hosted CI**

```bash
git add shared/procuresignal/demo tests/integration/test_demo_seed.py \
  frontend/playwright.config.ts frontend/e2e frontend/package.json frontend/package-lock.json \
  docker-compose.yml .github/workflows/ci.yml scripts/verify.sh docs/demo.md
git commit -m "Prove the buyer workflow in a real browser"
git push origin main
```

Wait for the system job on the exact commit to succeed before Task 3.

---

### Task 3: Evidence-based dead code, duplication, configuration, and documentation sweep

**Files:**
- Modify: `pyproject.toml`, `poetry.lock`
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/knip.json`
- Create: `jscpd.json`
- Create: `docs/engineering/repository-audit.md`
- Create: `docs/architecture/decisions.md`
- Create: `docs/production-readiness.md`
- Create: `docs/operations/content-licensing.md`
- Modify: `README.md`
- Modify: `docs/interview-preparation.md`
- Modify: `scripts/verify.sh`
- Delete: `docker/postgres-init/01-trust-host-auth.sh`
- Delete: `docker/postgres-init/02-set-password.sql`
- Delete after durable-content migration: `.superpowers/sdd/`, `docs/superpowers/`
- Modify or delete: only source files identified by the verified audit described below.

**Interfaces:**
- Produces quality commands `poetry run vulture api worker shared scripts --min-confidence 90`.
- Produces npm scripts `deadcode` (Knip) and `duplicates` (JSCPD).
- Produces durable production documents linked from README.

- [ ] **Step 1: Establish scanner baselines without deleting anything**

Add Vulture as a Poetry development dependency and Knip plus JSCPD as locked frontend dev dependencies. Configure Knip for the Next.js app, package scripts, Vitest, and Playwright entry points. Configure JSCPD for `api`, `worker`, `shared/procuresignal`, `scripts`, and frontend source with `minLines: 12`, `minTokens: 80`, and `threshold: 0`; exclude migrations, tests, generated privacy documents, lockfiles, `.next`, coverage, and Playwright artifacts because they are histories, assertions, or generated output rather than implementation duplication.

Run and save raw output outside the repository:

```bash
poetry run vulture api worker shared scripts --min-confidence 90 > /tmp/procuresignal-vulture.txt
cd frontend && npm run deadcode > /tmp/procuresignal-knip.txt
cd frontend && npm run duplicates > /tmp/procuresignal-jscpd.txt
poetry run ruff check . > /tmp/procuresignal-ruff.txt
```

Do not suppress exit codes while determining the baseline; run each separately and record its status.

- [ ] **Step 2: Classify every finding before editing**

For each reported symbol, file, dependency, or clone, verify all six evidence classes with `rg` and the relevant manifest/tooling:

1. Python/TypeScript references and dynamic import strings;
2. package exports and framework discovery;
3. Dockerfile and Compose inputs;
4. CI and shell scripts;
5. migrations, fixtures, and tests; and
6. README, runbook, or operator invocation.

Record the finding, evidence, decision (`remove`, `consolidate`, or `retain`), and framework reason for every retained scanner exception in `docs/engineering/repository-audit.md`. FastAPI route decorators, Celery task decorators, SQLAlchemy model registration, Alembic revisions, Next.js route files, and CLI `__main__` blocks count as dynamic entry points and are not dead.

- [ ] **Step 3: Write regression tests before each behavioral consolidation**

For every duplicate implementation selected for consolidation, add a focused test that names the shared behavior and fails when one caller diverges. Pure deletions require proof from Step 2 plus the unchanged complete test suite; behavior changes still follow red-green-refactor.

Remove the two `docker/postgres-init` files immediately after confirming Compose, Dockerfiles, scripts, and CI have no reference: the Compose comment already states those init scripts were dropped, so retaining them is stale and misleading. Replace the stale comment with the current password-auth behavior.

- [ ] **Step 4: Resolve every scanner finding honestly**

Delete proven-unused symbols/files/dependencies. Consolidate exact clones behind the domain owner already used by their callers. For legitimate dynamic entry points that scanners cannot infer, add the narrowest named entry or configuration declaration; do not add dummy calls, wildcard ignores, or test-only references whose sole purpose is making a scanner green.

Re-run all four scanners until they exit `0`. Every remaining exemption must appear by exact path/symbol in the audit document with its dynamic entry point.

- [ ] **Step 5: Audit hardcoded configuration and stale comments**

Search production source and infrastructure separately:

```bash
rg -n "(localhost|127\\.0\\.0\\.1|admin/admin|password|secret|token|api[_-]?key)" \
  api worker shared scripts docker docker-compose.yml prometheus.yml frontend \
  --glob '!**/*.test.*' --glob '!**/__tests__/**'
rg -n "TODO|FIXME|HACK|XXX|ponytail|temporary|for now|later" \
  api worker shared scripts docker frontend README.md docs
```

Classify findings as secret, deployment setting, local-development default, protocol/security invariant, fixture, or stale prose. Move deployment-dependent values into validated settings or documented Compose variables; retain security ceilings as named constants with rationale; remove stale narrative comments and comments that merely restate code. Add secret-resolution/config tests before moving any runtime value.

- [ ] **Step 6: Migrate durable documentation and remove process artifacts**

Create production documentation before deleting process files:

- `docs/architecture/decisions.md`: preserve D1–D7 from the canonical roadmap, updated to implemented reality.
- `docs/production-readiness.md`: completed capabilities, verification contract, known external blockers, and launch checklist.
- `docs/operations/content-licensing.md`: snippet/attribution/link-out behavior and the unresolved commercial-rights decision.
- existing privacy, recovery, SLO, and demo documents remain under their production paths.

Update README's features, architecture, commands, service ports, authentication, search, watchlists, notifications, agent approval, privacy, recovery, and documentation links. Update `docs/interview-preparation.md` so it no longer describes authentication or enterprise features as hypothetical and so the demo narrative matches the verified product.

Run:

```bash
rg -n "docs/superpowers|\.superpowers" . \
  --glob '!docs/superpowers/**' --glob '!.superpowers/**'
```

Resolve every reference, then remove `.superpowers/sdd/` and `docs/superpowers/`. Git history remains the implementation history; the working tree contains only durable product documentation.

- [ ] **Step 7: Add scanners to the unified verifier and run all non-system gates**

Add Vulture, Knip, and JSCPD to `lint` after compiler/linter checks. Run:

```bash
scripts/verify.sh lint
scripts/verify.sh backend
scripts/verify.sh frontend
scripts/verify.sh audit
scripts/verify.sh containers
git diff --check
```

Expected: every command exits `0`. Review the dated Python vulnerability ignore file against the current audit; remove fixed/obsolete IDs and update review dates only with current evidence.

- [ ] **Step 8: Commit, push, and confirm hosted CI**

Stage the complete reviewed cleanup explicitly, inspect `git diff --cached --stat` and `git diff --cached`, then:

```bash
git commit -m "Leave only the code and documentation the product uses"
git push origin main
```

Wait for every hosted job, including system/browser verification, on the exact commit.

---

### Task 4: Final clean-room verification and completion record

**Files:**
- Modify: `docs/production-readiness.md`
- Modify: `README.md` only if verification exposes an inaccurate command or prerequisite.

**Interfaces:**
- Consumes: `scripts/verify.sh all` and the GitHub Actions run for the final commit.
- Produces: a stable launch-checklist section listing external owner actions without embedding volatile CI run IDs or timestamps.

- [ ] **Step 1: Prove the repository is reproducible from a clean checkout**

Create a temporary clone of `origin/main` outside the working tree. Install dependencies only from `poetry.lock` and `frontend/package-lock.json`. Confirm no untracked local file from earlier tasks is required.

- [ ] **Step 2: Run release verification from empty state**

Remove ProcureSignal Compose containers and volumes, then run the documented setup and:

```bash
scripts/verify.sh all
```

Read complete output and record exit codes for all six leaf groups. Confirm the restore drill leaves no drill database, Playwright retains no failure artifacts on success, and `git status --short` remains empty except for intentionally generated ignored output.

- [ ] **Step 3: Recheck requirements line by line**

Compare the approved completion spec's eight success criteria with concrete evidence:

- generated privacy record check;
- restore receipt and cleanup;
- loaded SLO rules and provisioned dashboard;
- unified verification output;
- browser critical-path output;
- repository audit with zero scanner findings;
- production documentation links; and
- exact-commit hosted CI success.

Any missing evidence reopens the owning task; do not weaken a criterion or edit a test to match a failure.

- [ ] **Step 4: Finalize the production-readiness document**

Mark buildable Phases 7–9 complete and list only these external launch actions when still unresolved: hosting/EU residency, off-host backup scheduling, SMTP credentials, content licensing, GDPR legal sign-off, and optional collaboration-channel credentials. Keep “engineering complete”, “demo ready”, and “production launch ready” as separate verdicts.

- [ ] **Step 5: Commit documentation corrections, push, and verify exact SHA**

If Step 4 changes tracked files:

```bash
git add docs/production-readiness.md README.md
git commit -m "Record what remains before a production launch"
git push origin main
```

Run or wait for GitHub Actions on the final exact SHA. The implementation is not reported complete until all required hosted jobs conclude successfully.

## Self-Review

- **Spec coverage:** Task 1 unifies verification; Task 2 proves the browser workflow; Task 3 covers dead code, DRY, stale/hardcoded content, folder cleanup, and durable docs; Task 4 performs clean-room and hosted verification.
- **Type consistency:** CI, local development, and final verification all call the same `scripts/verify.sh` group interface. Demo tests, CLI, and Playwright all consume the same guarded seed contract.
- **Review-focus coverage:** precondition failure, session reload, seed safety, framework-aware deletion, and CI/local parity each have an explicit test or verification step.
- **No silent external claims:** real SMTP, hosting, legal approval, commercial content rights, and cloud recovery remain named owner actions rather than simulated successes.
