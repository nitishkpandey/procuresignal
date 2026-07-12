# Task 6 Report: Frontend Risk Events Page

## Delivered

- Added typed risk event contracts and API client functions for fetching events and updating status.
- Added the localized Risks navigation item in English, German, French, and Spanish.
- Added the `/risk-events` route and a compact, bordered risk-event list with loading, empty, error/retry, and status-update states.
- Confidence is rendered as a rounded number followed only by `%`.
- Added API, header navigation, rendering, and status-update tests.

## Verification

- `npm run test:run -- api.test.ts risk-events-view.test.tsx header.test.tsx`: 18 tests passed across 4 files.
- `npm run typecheck`: passed.
- `npm run lint`: passed with no ESLint warnings or errors.

## Scope

Only the Task 6 frontend files are intended for the implementation commit. Existing untracked duplicate/generated artifacts remain untouched.

## Review Fix: Risk Event Status Mutation

- Disabled each risk event status select while its update request is pending to prevent overlapping PATCH requests.
- Restored the status captured immediately before the attempted change when the request fails.
- Added regression coverage for pending-state disabling, failed-update rollback, and re-enabling the select.

## Review Fix Verification

- `cd frontend && npm run test:run -- risk-events-view.test.tsx`: 3 tests passed.
- `cd frontend && npm run typecheck`: passed.
- `cd frontend && npm run lint`: passed with no ESLint warnings or errors.
- `git diff --check`: passed.
