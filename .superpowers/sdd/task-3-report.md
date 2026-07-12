# Task 3 Report: Idempotent Risk Event Persistence

## Status

Complete.

## Changes

- Added `build_event_key` with normalized, order-independent supplier/location inputs.
- Added async recent-article scanning with configurable lookback and limit.
- Added idempotent risk-event create/update persistence with one batch commit.
- Added per-article error isolation and generation counters.
- Added focused tests for stable keys, idempotency, and skipped article failures.

## Verification

- TDD red: the focused test module reached the expected missing persistence-module import failure.
- `PYTHONPATH=shared ./.venv/bin/pytest tests/unit/test_risk_event_persistence.py -q` passed, 3 tests.
- `PYTHONPATH=shared ./.venv/bin/pytest tests/unit/test_risk_event_detector.py tests/unit/test_models.py -q` passed, 13 tests.
- `./.venv/bin/ruff check shared/procuresignal/risk_events/persistence.py tests/unit/test_risk_event_persistence.py` passed.
- Poetry is unavailable, so focused tests used the repository `.venv` with `PYTHONPATH=shared`.

## Concerns

Pre-existing unrelated untracked artifacts remain in the worktree and were not staged or modified.
