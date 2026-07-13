# Phase 1 Repository Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove generated, duplicate, stale, and conclusively dead code without changing ProcureSignal product behavior, then prove the repository remains healthy.

**Architecture:** Treat cleanup as an evidence pipeline: establish a baseline, classify artifacts and duplicate content, audit runtime wiring before dead-code removal, add narrow recurrence safeguards, and finish with the same full-stack gates used by CI. Canonical tracked files remain the source of truth unless a duplicate contains a current behavior or regression test that is demonstrably missing.

**Tech Stack:** Git, Python 3.11, Poetry, FastAPI, Celery, APScheduler, Pytest, Black, Ruff, MyPy, Next.js 14, TypeScript, ESLint, Vitest, Docker Compose.

## Global Constraints

- Do not change product behavior, API contracts, database schemas, or UI flows.
- Do not implement Phase 2 cost optimization or change LLM behavior.
- Preserve `docs/interview-preparation.md` untracked until Phase 10.
- Do not delete uncertain dynamically wired code; record it as retained with evidence.
- Do not weaken tests, lint, type checking, or builds to make cleanup pass.
- Keep every commit focused and independently verifiable.

## File Map

- Modify: `.gitignore` — prevent numbered coverage databases and stale Next.js build directories from recurring.
- Delete: `.coverage 2` through `.coverage 10` — generated local coverage databases.
- Delete: `frontend/.next-stale-webpack-runtime-20260710/` — generated stale Next.js output.
- Delete after comparison: `frontend/__tests__/* 2.ts*`, `shared/procuresignal/**/* 2.py`, and `tests/**/* 2.py` — duplicate-suffixed files.
- Modify only if unique current behavior is missing: the canonical counterpart of a differing duplicate.
- Modify/delete only when the dead-code evidence standard is satisfied: tracked Python/TypeScript production files discovered by the audit.
- Preserve unchanged and untracked: `docs/interview-preparation.md`.

---

### Task 1: Capture The Baseline And Classify Duplicates

**Files:**
- Inspect: `.github/workflows/ci.yml`
- Inspect: `pyproject.toml`
- Inspect: `frontend/package.json`
- Inspect: every duplicate-suffixed file and its canonical counterpart listed by `find`
- Create temporarily outside Git: `/tmp/procuresignal-phase1-baseline.txt`

**Interfaces:**
- Consumes: the approved Phase 1 design and the current `main` worktree.
- Produces: baseline verification output and an evidence-backed duplicate classification used by Tasks 2 and 3.

- [ ] **Step 1: Record repository state and the exact artifact inventory**

Run:

```bash
git status --short --branch
find . -type f -name '* 2.*' -o -type f -name '.coverage *'
du -sh frontend/.next-stale-webpack-runtime-20260710
```

Expected: `main` contains the approved design commit; the only known untracked items are the deferred interview document and Phase 1 cleanup candidates; the stale Next.js directory is approximately 291 MB.

- [ ] **Step 2: Run and capture the backend baseline**

Run:

```bash
poetry run black --check .
poetry run ruff check .
poetry run mypy api worker shared
poetry run pytest tests -v
```

Expected: each command exits 0. If a command already fails, save its exact failure and do not attribute it to later cleanup.

- [ ] **Step 3: Run and capture the frontend baseline**

Run from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test:run
```

Expected: each command exits 0. Do not run `next build` before removing the stale build directory because the handoff identifies prior cache collisions.

- [ ] **Step 4: Compare every duplicate with its canonical file**

Run from the repository root:

```bash
find frontend shared tests -type f -name '* 2.*' -print0 | while IFS= read -r -d '' duplicate; do canonical=${duplicate/ 2/}; echo "### $duplicate -> $canonical"; diff -u "$duplicate" "$canonical" || true; done
```

Expected: identical `__init__ 2.py` files have no diff; the differing duplicates are older snapshots whose canonical counterparts include later currency, language, risk-event, retention, and CI-isolation work. If any duplicate instead contains unique current logic, identify the exact hunk and its required canonical test before Task 2.

- [ ] **Step 5: Commit only if a canonical file needed a missing regression test**

If no unique current logic exists, make no commit. If unique current logic exists, first add a failing test to the canonical test file, run the exact test and confirm it fails, integrate the smallest canonical fix, rerun and confirm it passes, then commit only those canonical files:

```bash
git diff --name-only
git add -u
git commit -m "fix: preserve behavior from duplicate snapshot"
```

Expected: a focused commit only when preservation was necessary; otherwise the task ends with no tracked diff.

### Task 2: Remove Generated And Duplicate Artifacts Safely

**Files:**
- Modify: `.gitignore`
- Delete: `.coverage 2` through `.coverage 10`
- Delete: `frontend/.next-stale-webpack-runtime-20260710/`
- Delete: all duplicate-suffixed files under `frontend/`, `shared/`, and `tests/`
- Preserve: `docs/interview-preparation.md`

**Interfaces:**
- Consumes: Task 1 duplicate classification.
- Produces: a clean artifact-free worktree and narrow ignore patterns used by all later tasks.

- [ ] **Step 1: Add recurrence safeguards**

Add these exact lines to the Testing section of `.gitignore`:

```gitignore
.coverage *
```

Add this exact line beside the existing frontend `.next/` rule in `frontend/.gitignore`:

```gitignore
.next-stale-*/
```

- [ ] **Step 2: Verify the new patterns target only known artifacts**

Run:

```bash
git check-ignore -v '.coverage 2' frontend/.next-stale-webpack-runtime-20260710/BUILD_ID
git check-ignore -v docs/interview-preparation.md || true
```

Expected: the first two paths match the new rules; `docs/interview-preparation.md` does not match an ignore rule.

- [ ] **Step 3: Delete the classified generated and duplicate paths**

Run:

```bash
rm -f '.coverage 2' '.coverage 3' '.coverage 4' '.coverage 5' '.coverage 6' '.coverage 7' '.coverage 8' '.coverage 9' '.coverage 10'
rm -rf frontend/.next-stale-webpack-runtime-20260710
find frontend shared tests -type f -name '* 2.*' -delete
```

Expected: only paths classified in Task 1 are deleted; no canonical tracked file is removed.

- [ ] **Step 4: Prove artifact cleanup and document preservation**

Run:

```bash
find . -type f -name '* 2.*' -o -type f -name '.coverage *'
find frontend -maxdepth 1 -type d -name '.next-stale-*'
test -f docs/interview-preparation.md
git status --short
```

Expected: both `find` commands print nothing; the `test` command exits 0; status shows only `.gitignore`, `frontend/.gitignore`, the implementation plan, and the preserved interview document.

- [ ] **Step 5: Commit recurrence safeguards**

```bash
git add .gitignore frontend/.gitignore
git commit -m "chore: ignore recurring local artifacts"
```

Expected: the commit contains only the two narrow ignore-rule changes. Untracked deletions do not appear in Git because the deleted artifacts were never tracked.

### Task 3: Audit Runtime Wiring And Remove Proven Dead Code

**Files:**
- Inspect: `api/**/*.py`, `worker/**/*.py`, `shared/procuresignal/**/*.py`
- Inspect: `frontend/app/**/*.{ts,tsx}`, `frontend/components/**/*.{ts,tsx}`, `frontend/lib/**/*.{ts,tsx}`, `frontend/store/**/*.{ts,tsx}`
- Inspect: `.github/workflows/ci.yml`, `docker-compose.yml`, `Dockerfile.api`, `Dockerfile.worker`, `scripts/*.py`
- Modify/delete: only exact candidates that pass every evidence check below

**Interfaces:**
- Consumes: the clean canonical tree from Task 2.
- Produces: production code with conclusively unused units removed and uncertain framework-wired units retained.

- [ ] **Step 1: Let configured tooling identify unused imports and unreachable references**

Run:

```bash
poetry run ruff check api worker shared tests --select F401,F811,F821,F841
poetry run mypy api worker shared
cd frontend && npm run lint && npm run typecheck
```

Expected: commands either pass or report exact candidates. Treat every report as a candidate, not automatic deletion.

- [ ] **Step 2: Enumerate framework entry points before reference counting**

Run from the repository root:

```bash
rg -n 'include_router|APIRouter|@router|@app|celery_app|@.*task|add_job|SCHEDULED_JOB_IDS|dynamic\(|import\(|process\.env|scripts/|command:|entrypoint:' api worker shared frontend docker-compose.yml Dockerfile.* .github scripts
```

Expected: a reviewable map of routes, Celery tasks, scheduler jobs, Next.js conventions, environment-driven behavior, scripts, Docker commands, and CI entry points. Anything present here is retained unless its registration itself is proven obsolete.

- [ ] **Step 3: Check each candidate across source, tests, configuration, and Git history**

For each exact candidate symbol or path reported in Step 1 or noticed during inventory, run:

```bash
rg -n --hidden --glob '!.git/**' 'candidate_symbol_copied_from_step_1' .
git log --oneline --all -- path/copied/from/step_1.py
git blame path/copied/from/step_1.py
```

Expected: remove only a candidate with no consumer, no framework/configuration registration, no supported test behavior, and no newer logic hidden by duplication. Retain uncertain candidates and note the dynamic or contractual reason in the task report.

- [ ] **Step 4: Add or identify the protecting test before each removal**

Run the narrowest existing test covering the candidate's surrounding unit before editing, for example:

```bash
poetry run pytest tests/unit/test_scheduler.py -v
poetry run pytest tests/unit/test_currency.py -v
cd frontend && npm run test:run -- __tests__/api.test.ts
```

Expected: the relevant test passes before removal. If no test covers surrounding supported behavior, add a focused test that asserts the public behavior, confirm it passes before removal, then use it as the regression gate.

- [ ] **Step 5: Remove only the proven-dead import, symbol, module, or component**

Use a focused patch containing the exact proven candidate. Do not refactor neighboring live code. Then rerun the narrow test from Step 4.

Expected: the narrow test passes and the runtime registration/reference map remains intact.

- [ ] **Step 6: Repeat Steps 3–5 per independent candidate and commit separately**

```bash
git diff --name-only
git add -u
git commit -m "refactor: remove proven unused code"
```

Expected: one independently reviewable commit per unrelated dead-code unit. If no production code meets the evidence threshold, make no dead-code commit and record that the audit found no safe removal candidates.

### Task 4: Run Full Verification And Review The Final Diff

**Files:**
- Inspect: all tracked changes since `be99b70`
- Verify: complete backend and frontend trees
- Preserve: `docs/interview-preparation.md`

**Interfaces:**
- Consumes: Tasks 1–3 outputs.
- Produces: evidence that Phase 1 is complete without behavior regression.

- [ ] **Step 1: Run backend formatting, lint, typing, and tests**

Run:

```bash
poetry run black --check .
poetry run ruff check .
poetry run mypy api worker shared
poetry run pytest tests -v
```

Expected: all commands exit 0; Pytest reports no failures.

- [ ] **Step 2: Run frontend lint, typing, tests, and production build**

Run from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test:run
npm run build
```

Expected: all commands exit 0; Vitest reports no failures; Next.js completes a production build.

- [ ] **Step 3: Verify Docker Compose configuration remains valid**

Run:

```bash
docker compose config --quiet
```

Expected: exit 0 with no configuration error.

- [ ] **Step 4: Verify hygiene success criteria**

Run:

```bash
find . -type f -name '* 2.*' -o -type f -name '.coverage *'
find frontend -maxdepth 1 -type d -name '.next-stale-*'
test -f docs/interview-preparation.md
git status --short
git diff be99b70..HEAD --check
git diff --stat be99b70..HEAD
git log --oneline be99b70..HEAD
```

Expected: no duplicate/generated paths; interview document still exists; no whitespace errors; commit history is focused; no unintended product, schema, API, or UI change appears in the diff.

### Task 5: Phase 1 Completion Record

**Files:**
- Create: `docs/superpowers/reports/2026-07-13-phase-1-repo-hygiene.md`

**Interfaces:**
- Consumes: final command output and commit history from Task 4.
- Produces: an auditable Phase 1 record and clean handoff into a separately designed Phase 2.

- [ ] **Step 1: Write the completion record with exact evidence**

Create a Markdown report titled `Phase 1 Repository Hygiene Report`. Include sections named `Removed Artifacts`, `Duplicate Review`, `Dead-Code Audit`, `Safeguards`, `Verification`, and `Deferred Intentionally`. Record the observed artifact counts and stale-directory size from Task 1, the disposition of every duplicate family, evidence for every dead-code removal or the explicit result that none qualified, and the exact pass/fail and test counts printed by every Task 4 command. State verbatim that `.coverage *` and `.next-stale-*/` are the new safeguards and that `docs/interview-preparation.md` remains local and untracked until Phase 10.

- [ ] **Step 2: Check the report and repository diff**

Run:

```bash
rg -n 'T[B]D|T[O]DO|F[I]XME|fill.in|result.goes.here' docs/superpowers/reports/2026-07-13-phase-1-repo-hygiene.md
git diff --check
git status --short
```

Expected: the placeholder scan prints nothing; only the completion report and the intentionally deferred interview document remain untracked or modified.

- [ ] **Step 3: Commit the completion record**

```bash
git add docs/superpowers/reports/2026-07-13-phase-1-repo-hygiene.md
git commit -m "Document Phase 1 repository hygiene results"
```

Expected: a documentation-only commit recording exact evidence. Phase 2 begins only after Phase 1 is confirmed green and receives its own brainstorming/design cycle.
