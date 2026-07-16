# Task 6 Report: Orchestration, Persistence, Claims, and Worker Metrics

## Outcome

Implemented registry-backed retrieval orchestration with durable run/source claims, stale-lease recovery, bounded global/per-host concurrency, partial-failure isolation, exact provider closure, provenance persistence, separate within-run/database duplicate metrics, redacted failure enums, and additive Celery worker metrics. The disabled structured-sanctions source remains disabled and no sanctions adapter was added.

## TDD evidence

### Red

1. `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -v`
   - Exit 127 because this worktree does not contain `.venv`; no tests ran.
2. `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -v`
   - Exit 2 during collection with `ModuleNotFoundError: No module named 'procuresignal.retrieval.orchestrator'`, the expected missing-feature failure.
3. `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_tasks.py -k retrieve -v`
   - Exit 1: worker module lacked `RetrievalOrchestrator`, the expected worker-integration failure.

### Green

1. `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -v`
   - Exit 0: 3 passed.
2. `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py -k 'retrieval or retrieve' -v`
   - Exit 0: 4 passed, 14 deselected.
3. `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_tasks.py tests/integration/test_api.py -v`
   - Exit 0: 104 passed (final fresh run after formatting and cleanup).
4. `../../.venv/bin/ruff check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py`
   - Initial exit 1 identified formatting/import issues; corrected with `ruff format` and `ruff check --fix`.
5. `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/orchestrator.py shared/procuresignal/retrieval/persistence.py worker/tasks.py`
   - Final exit 0: success, no issues in 3 source files.
6. `git diff --check`
   - Exit 0, no whitespace errors.

## Files changed

- `shared/procuresignal/retrieval/orchestrator.py`: result contracts, run-key claim/idempotency, stale reclaim, source claims, global six/per-host two semaphores, partial-failure handling, sanitized failure codes, lifecycle closure, aggregation and next-poll metrics.
- `shared/procuresignal/retrieval/persistence.py`: all registry provenance fields, dialect-correct conflict inserts, and row savepoints.
- `shared/procuresignal/retrieval/base.py`: parser failure enum.
- `shared/procuresignal/retrieval/__init__.py`: public orchestration exports.
- `worker/tasks.py`: one registry-backed orchestration path and legacy-plus-additive result payload.
- `tests/unit/test_retrieval_orchestrator.py`: concurrency, partial failures, closure, claims, stale reclaim, rerun behavior, provenance, and duplicate-counter coverage.
- `tests/unit/test_tasks.py`: worker result compatibility/audit metrics.

`docs/interview-preparation.md` and `tests/integration/test_api.py` were not modified. The existing integration suite was run in full as required and passed.

## Self-review

- Run and source claims commit before any network request.
- Source outcomes and run completion occur in short transactions after fetch/persistence.
- Two semaphores enforce six total and two per endpoint hostname.
- Exceptions are exposed only as enum values; exception strings are neither persisted nor returned.
- Every constructed provider is closed once from `finally`.
- Persistence uses a nested transaction per row plus conflict-ignore, so an invalid row cannot erase previously successful inserts.
- Provenance maps all Task 1 fields to `NewsArticleRaw`.
- Structured sanctions remains explicitly absent because its registry entry is disabled and the default factory rejects non-RSS adapters.
- Worker retains `status`, `articles_fetched`, `articles_inserted`, `duplicates`, `errors`, `providers`, and `timestamp`, while adding run/source audit metrics.

## Concerns

- The brief's literal `.venv/bin/pytest` path is absent inside the worktree; the repository-root environment at `../../.venv` was used.
- Existing NewsAPI/GDELT provider classes remain available, but the worker now follows the reviewed default-enabled registry. The catalog contains no enabled NEWSAPI/GDELT source definitions, so they are not a parallel execution path. Adding such definitions would require a separately reviewed registry/snapshot change.
