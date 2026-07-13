# Task 3 Report: Runtime Wiring and Dead-Code Audit

## Outcome

- Audited backend and frontend framework entry points, Docker commands, scheduler registrations, Celery tasks, scripts, and CI wiring.
- Found no production unit that satisfied every deletion criterion. No uncertain code was deleted.
- Reduced Ruff to 0 errors and MyPy (`api worker shared`) from 66 errors in 19 files to 0 errors.
- Preserved all API, schema, database, UI, and runtime behavior.

## Candidate and wiring evidence

The configured unused-code checks (`F401`, `F811`, `F821`, `F841`) reported no candidates. The broader runtime map confirmed:

- Every FastAPI router is included by `api/main.py`.
- Celery application and task decorators are live through Docker worker/beat commands and scheduler enqueue functions.
- All six `SCHEDULED_JOB_IDS` correspond to `scheduler.add_job` registrations.
- `scripts/bootstrap_pipeline.py` is invoked by Docker Compose.
- Next.js app routes/components and environment-dependent API/WebSocket URLs are convention/configuration wired.

Because static absence alone is insufficient for framework-driven code, all dynamically registered routes, tasks, jobs, scripts, and Next.js convention files were retained. No candidate had both zero references and zero runtime/configuration registration.

## Type-check remediation

- Added explicit engine/session-factory types and made the database URL fallback visibly non-optional.
- Added concrete Pydantic validator, API serializer/response, and scheduler option types.
- Widened signal normalization inputs to their honest runtime type while preserving historical stringification, including `None`.
- Materialized currency history values into a consistently typed list.
- Added missing-import handling only for third-party libraries without typing metadata; first-party code remains fully checked. Remaining `Any` annotations are limited to genuinely dynamic JSON, Pydantic validator, Celery task, SQLAlchemy expression, and untyped third-party response boundaries.

## Commands and results

```text
PYTHONPATH=shared .../.venv/bin/ruff check api worker shared tests --select F401,F811,F821,F841
0 errors

PYTHONPATH=shared .../.venv/bin/ruff check api worker shared tests
0 errors

PYTHONPATH=shared .../.venv/bin/mypy api worker shared
Success: no issues found in 80 source files

PYTHONPATH=shared .../.venv/bin/pytest -q
142 passed in 3.97s

.../.venv/bin/black api worker shared
80 files clean after one formatting-only adjustment
```

## Commit

- `6d6e89e chore: enforce clean backend type checks`
- `7744a15 fix: address repository audit review`
- `af7e5e1 fix: model dynamic types explicitly`

Final verification: focused personalization and risk/API tests passed (49), Ruff passed, MyPy found no issues in 80 files, and the full backend suite passed with 143 tests.

## Self-review

- No public contract, schema, migration, UI, or runtime flow changed.
- Assertions in the signals router encode the invariant already established by the preceding database-configured guard; they do not alter successful runtime paths.
- MyPy overrides apply only to third-party packages without typing metadata.
- No dead-code deletion was justified by the evidence threshold, so the safe result is an audited retention decision rather than speculative removal.
- `docs/interview-preparation.md` was not modified.

## Reviewer-finding remediation

- Removed all broad first-party MyPy overrides covering worker tasks, preferences, chat, retention, retrieval persistence, and risk detection. Replaced them with explicit parameter/return types and exact dynamic-result access via `getattr`.
- Restored matcher behavior exactly and widened signal normalization to `Iterable[object]`, matching its existing `str(value)` implementation without an unsafe cast.
- Restored exact `DATABASE_URL` semantics: an explicitly empty environment value is not replaced by the worker default.
- Added literal verification and runtime/history/blame evidence in `.superpowers/sdd/task-3-evidence.txt`.
- Frontend ESLint and TypeScript checks both pass.
- Removed the final first-party override for `api.routers.risk_events`; SQLAlchemy statements and expressions now have explicit `Select`/`ColumnElement` annotations.
