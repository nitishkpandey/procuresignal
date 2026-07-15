# Task 3 Report: Safe Fetching, Retry Classification, and Circuits

## Result

Implemented URL safety validation, bounded streaming fetches, retry classification,
per-source circuit behavior, and atomic durable retrieval claims/outcomes.

## TDD evidence

- Red: focused collection failed with three `ModuleNotFoundError` errors for
  `retrieval.security`, `retrieval.fetching`, and `retrieval.audit`.
- Green: `17 passed in 1.46s` for the three focused unit files plus the retrieval audit
  migration integration test.
- Full: `287 passed in 6.53s`.
- Static: Black left 18 files unchanged; Ruff reported no issues; mypy reported success
  across 13 retrieval source files.

## Security and concurrency coverage

- HTTPS-only, no credentials, exact host allowlist, public-only DNS answers, private,
  loopback, link-local, literal IP, and IPv4-mapped IPv6 rejection.
- Initial and redirect destination validation, redirect bound, decoded streaming byte cap,
  structured failures, `Retry-After`, retryable 429/5xx/network failures, and deterministic
  content-type rejection without retry.
- Circuit opens after five consecutive failed fetches, becomes half-open after cooldown,
  and resets on success.
- PostgreSQL candidate reads use `FOR UPDATE SKIP LOCKED`; both PostgreSQL and SQLite use
  a conditional owner/expiry update, commit before network work, recover stale leases, and
  atomically claim sources through the existing unique run/source outcome constraint.
- Persisted failure details accept only short safe tokens; exception messages and response
  bodies are not stored.

## Commit

Pending at report creation; populated in the final handoff.

## Concerns

- The URL policy rejects unsafe DNS answers on every request/redirect validation. Complete
  connection-level DNS pinning depends on the injected HTTP transport honoring the validated
  resolution; callers must not inject a transport with an independent untrusted resolver.
- Circuit counters are process-local; durable run/source ownership and outcomes are database
  backed, but cross-process circuit aggregation is not represented by the current Task 1/2
  schema.
