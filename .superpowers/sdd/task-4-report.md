# Task 4: Risk Events API Report

## Status

Implemented the Risk Events API layer.

## Delivered

- Added `RiskEventItem`, list response, and status-update schemas.
- Added risk event list, detail, and status-update endpoints.
- Generates recent persisted risk events before listing when needed.
- Supports scalar risk filters, JSON-list contains filters, preference-aware deterministic ranking, and response translation of evidence and recommendations only.
- Registered the risk events router with the FastAPI application.
- Added integration coverage for list generation and status updates, and updated the seeded article to produce a strike event.

## Verification

```text
PYTHONPATH=shared .venv/bin/pytest tests/integration/test_api.py -q
25 passed in 2.04s
```

`git diff --check` and `PYTHONPATH=shared .venv/bin/python -m compileall -q api` also completed successfully.

## Notes

The environment did not provide Poetry or an installed project package, so tests were run through `.venv` with `PYTHONPATH=shared`.

## Pagination Review Fix

- Removed the SQL `limit + offset` window from risk event candidate retrieval so scalar-filtered events are fully considered before JSON-list filtering, preference ranking, total counting, and pagination.
- Added integration coverage with five events, exceeding the requested page window, that verifies an older Bosch-preferred event is returned after ranking and that `total_count` remains five.

### Verification

```text
PYTHONPATH=shared .venv/bin/pytest tests/integration/test_api.py -q
26 passed in 3.13s

PYTHONPATH=shared .venv/bin/ruff check api/routers/risk_events.py tests/integration/test_api.py
All checks passed!

git diff --check
```
