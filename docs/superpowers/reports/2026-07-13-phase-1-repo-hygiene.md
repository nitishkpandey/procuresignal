# Phase 1 Repository Hygiene Report

## Removed Artifacts

Phase 1 removed the following untracked artifacts from the original checkout using an explicit allowlist:

- nine numbered coverage databases, `.coverage 2` through `.coverage 10`;
- one 291 MB stale Next.js build directory, `frontend/.next-stale-webpack-runtime-20260710`;
- 12 scoped source/test duplicates reviewed below.

The final scoped scans found none of these artifacts in either the original checkout or the Phase 1 worktree. Generated duplicate-suffixed files inside ignored dependency and cache trees were outside the source-hygiene scope.

## Duplicate Review

All 12 scoped duplicates were obsolete. Two were byte-identical copies and ten were older or superseded snapshots with no unique current behavior or test coverage.

| Removed duplicate | Disposition |
|---|---|
| `frontend/__tests__/api.test 2.ts` | Superseded by the canonical test's language, translation, preference, currency, and risk-event coverage. |
| `frontend/__tests__/currency-view.test 2.tsx` | Superseded by current compact-monitor, currency-universe, buy-window, and show-all coverage. |
| `frontend/__tests__/preference-form.test 2.tsx` | Superseded by current language-state and header-control coverage. |
| `shared/procuresignal/currency/__init__ 2.py` | Byte-identical to the canonical file. |
| `shared/procuresignal/currency/service 2.py` | Superseded by the expanded quote universe, provider fallback, row-payload parsing, and robust date extraction. |
| `shared/procuresignal/jobs/__init__ 2.py` | Byte-identical to the canonical file. |
| `shared/procuresignal/jobs/retention 2.py` | Superseded by risk-event retention and deletion reporting. |
| `tests/integration/test_api 2.py` | Superseded by current database isolation, currency, risk-event, translation, inference, and feed coverage. |
| `tests/unit/test_currency 2.py` | Superseded by global-default, provider-fallback, and row-payload coverage. |
| `tests/unit/test_enrichment 2.py` | Strict older subset of the canonical test. |
| `tests/unit/test_retention 2.py` | Superseded by risk-event retention and deletion-count coverage. |
| `tests/unit/test_scheduler 2.py` | Strict older subset of the canonical test. |

## Dead-Code Audit

No production dead code met the proof threshold for removal. Ruff's `F401`, `F811`, `F821`, and `F841` checks produced no candidates, and the runtime audit found framework or configuration consumers for every FastAPI router, Celery task, scheduled job, bootstrap script, and Next.js convention entry point examined. Nothing had both zero references and zero runtime/configuration registration, so no production unit was deleted speculatively.

## Safeguards

`.coverage *` and `.next-stale-*/` are the new safeguards.

The first rule is in the repository `.gitignore`; the second is in `frontend/.gitignore`. `git check-ignore` confirmed both rules match their intended recurrence patterns and confirmed that the deferred interview document is not ignored.

## Verification

Every final Phase 1 verification command exited 0.

| Area | Exact final result |
|---|---|
| Black | `117 files would be left unchanged.` |
| Ruff | No diagnostics. |
| MyPy | `Success: no issues found in 80 source files` |
| Backend tests | 143 tests collected; 143 passed in 3.57 seconds. |
| Frontend lint | No ESLint warnings or errors. |
| Frontend typecheck | `tsc --noEmit` completed without diagnostics. |
| Frontend tests | 16 files and 52 tests passed in 2.62 seconds. |
| Frontend build | Next.js 14.2.35 compiled successfully and generated 8/8 static pages. |
| Alembic | One head, `e5f6a7_add_risk_event_scan_tracking (head)`, with a complete linear history from `<base>`. |
| Docker Compose | `docker compose config --quiet` exited 0 with no output. |

The frontend test run emitted only the non-failing Vite CJS deprecation warning, and the build emitted only non-failing Node `localStorage` experimental warnings. Alembic's required post-path-bootstrap model import is documented with a narrow `# noqa: E402`; migration order and behavior are unchanged.

## Deferred Intentionally

`docs/interview-preparation.md` remains local and untracked until Phase 10.

Its preservation was verified in the original checkout. It was not opened, modified, copied, deleted, staged, or added to an ignore rule during Phase 1. Phase 2 starts only after this green Phase 1 record and receives its own brainstorming and design cycle.
