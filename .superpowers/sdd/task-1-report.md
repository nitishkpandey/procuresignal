# Task 1 Report: Baseline and Duplicate Classification

## Result

**DONE_WITH_CONCERNS** — all cleanup candidates were inventoried and classified. No duplicate contains unique current logic, so no product code or regression test was changed and no commit was created. The baseline reproduces two acknowledged pre-existing quality failures: Ruff has one `E402` in `migrations/env.py`, and MyPy has 66 errors in 19 files.

## Repository and Artifact Inventory

- Original checkout: `main...origin/main [ahead 3]`, HEAD `02475da chore: ignore local worktrees`.
- Isolated worktree: `codex/phase-1-repo-hygiene`; its only untracked entry is the intentional `frontend/node_modules` symlink.
- Original checkout has nine untracked parallel coverage databases: `.coverage 2` through `.coverage 10`.
- Original checkout has 12 untracked source/test duplicates listed below.
- `frontend/.next-stale-webpack-runtime-20260710` is untracked and 291 MB.
- `docs/interview-preparation.md` is untracked and deferred; it was not opened, modified, or deleted.
- The literal repository-wide `find` returns 2,201 `* 2.*` files. Of these, 2,189 are generated/dependency artifacts: 2,103 under `frontend/node_modules`, 33 in the stale Next cache, 48 in `.venv`, and 5 Python bytecode files under test `__pycache__` directories. These are not source counterparts and should be removed only with their generated parent artifacts in later cleanup.

## Baseline Verification

Full command output is stored outside Git at `/tmp/procuresignal-phase1-baseline.txt`. Backend commands used direct executables from the shared `.venv` with `PYTHONPATH=shared`, as required by the handoff.

The durable inventory and comparison record is `.superpowers/sdd/task-1-evidence.txt`. It records the original-checkout cwd, exact executed commands, raw Git status, scoped artifact inventory, stale-directory size, SHA-256 hashes for both sides of every duplicate pair, and each complete unified diff (or `IDENTICAL`).

The controller explicitly authorized substituting direct executables from `/Users/nitishkumarpandey/Desktop/procuresignal/.venv/bin` with `PYTHONPATH=shared` because Poetry is unavailable in this environment. This is equivalent for these checks to `poetry run`: it invokes the same installed Black, Ruff, MyPy, and Pytest tools and dependencies from the repository's reusable virtual environment, while `PYTHONPATH=shared` supplies the package import path that Poetry's installed-project environment would otherwise provide.

| Check | Exit | Result |
|---|---:|---|
| Black `--check .` | 0 | 117 files unchanged |
| Ruff `check .` | 1 | Pre-existing `migrations/env.py:13:1 E402`; 1 error |
| MyPy `api worker shared` | 1 | Pre-existing 66 errors in 19 files; 80 source files checked |
| Pytest `tests -v` | 0 | 142 passed in 3.64s |
| Frontend lint | 0 | No warnings or errors |
| Frontend typecheck | 0 | Passed |
| Frontend Vitest | 0 | 16 files, 52 tests passed |

No `next build` was run.

Vitest also emitted the Vite warning `The CJS build of Vite's Node API is deprecated`; this is non-failing baseline noise and the command still exited 0 with all 52 tests passing.

## Duplicate Classification

Each source/test duplicate in the original checkout was compared byte-for-byte and with a unified diff against its canonical counterpart.

| Duplicate | Classification and evidence |
|---|---|
| `frontend/__tests__/api.test 2.ts` | Older snapshot (64 vs 112 lines). Canonical retains the existing API tests and adds language parameters, article translation, language preference patching, backend-selected currency defaults, and risk-event API coverage. |
| `frontend/__tests__/currency-view.test 2.tsx` | Older UI snapshot (35 vs 65 lines). Canonical tests the current compact EUR monitor, expanded currency universe, buy-window labels, and show-all interaction. Removed assertions refer to superseded labels/markup. |
| `frontend/__tests__/preference-form.test 2.tsx` | Older UI snapshot. Canonical initializes current language state and correctly verifies that the language control lives in the header rather than being duplicated in the preference form. |
| `shared/procuresignal/currency/__init__ 2.py` | Byte-identical to canonical (same SHA-256). Pure duplicate. |
| `shared/procuresignal/currency/service 2.py` | Older implementation (164 vs 271 lines). Canonical retains the original monitor flow and adds the expanded global quote universe, provider-failure fallback, Frankfurter row-payload parsing, and robust as-of extraction. |
| `shared/procuresignal/jobs/__init__ 2.py` | Byte-identical to canonical (same SHA-256). Pure duplicate. |
| `shared/procuresignal/jobs/retention 2.py` | Older implementation (61 vs 69 lines). Canonical retains existing pruning and adds risk-event retention/deletion reporting. |
| `tests/integration/test_api 2.py` | Older snapshot (286 vs 762 lines). Canonical retains the earlier endpoint tests and adds CI database isolation, currency defaults, risk-event listing/filter/status/pagination, translation, entity inference, and feed fallback/top-up coverage. |
| `tests/unit/test_currency 2.py` | Older snapshot (69 vs 130 lines). Canonical retains original currency tests and adds global defaults, provider fallback, and row-payload coverage. |
| `tests/unit/test_enrichment 2.py` | Strict older subset (234 vs 263 lines). Canonical adds procurement-category, signal-alias, and low-cost-model default tests; no older assertion was lost. |
| `tests/unit/test_retention 2.py` | Older snapshot (145 vs 190 lines). Canonical retains previous retention/idempotency checks and adds old/recent risk-event coverage and deletion counts. |
| `tests/unit/test_scheduler 2.py` | Strict older subset (23 vs 58 lines). Canonical adds the risk-event scheduled job and retention logging coverage; no older assertion was lost. |

## Preservation Decision

The canonical files supersede all 12 source/test duplicates. The two `__init__` duplicates are identical; all ten differing files are older snapshots whose canonical counterparts either strictly add coverage/logic or update assertions for intentionally newer behavior. No unique current behavior or test hunk exists only in a duplicate. Therefore Task 1 required no failing regression test, canonical fix, tracked diff, or commit.

## Concerns / Handoff

1. Ruff and MyPy do not meet the brief's nominal “exit 0” expectation, but their exact failures match the approved pre-existing baseline and must not be attributed to cleanup.
2. Later cleanup should treat the 2,189 duplicate-suffixed files inside `node_modules`, `.venv`, stale `.next`, and `__pycache__` as generated artifacts, not individually curated source files.
3. Preserve `docs/interview-preparation.md` exactly as directed.
