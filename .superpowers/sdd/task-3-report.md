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

## Spec-rejection remediation (2026-07-15)

### Exact red evidence

Command:
`PYTHONPATH=shared .../.venv/bin/pytest tests/unit/test_retrieval_fetching.py tests/unit/test_retrieval_audit.py -q`

Observed collection failure before remediation:

- `ImportError: cannot import name 'SecureTransport' ... retrieval.fetching`
- `ImportError: cannot import name 'NewsRetrievalCircuit' ... procuresignal.models`
- Result: `2 errors in 1.50s`.

The first implementation iteration then exposed an expected model-parity failure:
SQLite rejected the inherited `id` plus `source_id` composite autoincrement primary key,
and the 503 classification assertion showed the new transient enum. This was corrected by
using the standard inherited primary key plus a unique source ID and matching migration.

### Exact green evidence

- Focused security/fetch/audit/migration command: `28 passed in 1.16s`.
- Full suite command: `298 passed in 6.14s`.
- Black: `19 files would be left unchanged`.
- Ruff: `Success: no issues found`.
- mypy: `Success: no issues found in 13 source files`.
- PostgreSQL offline SQL assertion verifies `FOR UPDATE SKIP LOCKED`.
- Populated SQLite migration test verifies source leases, durable circuit table, and downgrade.

### Remediated behavior

- The production httpcore network backend substitutes only the validated public IP at TCP
  connect time. The original registry hostname remains in the httpcore URL, HTTP Host header,
  and TLS `server_hostname`, preserving SNI and certificate verification while eliminating the
  DNS validation/connect TOCTOU. Arbitrary `AsyncClient`/transport injection is rejected.
- SafeFetcher owns its client, enforces connect 5s/read 20s/write 20s/pool 5s timeouts, limits
  redirects to exactly three, supports async context management and idempotent close, and caps
  valid finite numeric/date Retry-After values at 15 minutes using an injectable UTC clock.
- Only network/timeouts, 429, and transient 5xx retry. Deterministic 4xx/content-type/security
  failures execute once. Decoded response bodies remain capped at 5 MiB.
- Per-source circuits are durable: five consecutive failures open for 30 minutes, one atomic
  owner-scoped half-open probe is leased, and success resets state across sessions/processes.
- Run and source leases are fixed at 65 minutes. Source claims support stale recovery; all run
  and source terminal updates require the current unexpired owner. Failure codes accept only
  the structured enum allowlist.

### Remaining concern

- `PinnedHTTPTransport` necessarily adapts httpx/httpcore transport internals available in the
  pinned dependency versions; upgrades of those libraries must run the offline pinning tests.
