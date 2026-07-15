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

## Second re-review remediation (2026-07-15)

### Exact red evidence

Command:
`PYTHONPATH=shared .../.venv/bin/pytest tests/unit/test_retrieval_fetching.py -q`

Observed before implementation: `16 failed, 3 passed in 0.95s`. Failures included missing
`SafeFetcher._for_test`, non-positive/high bound handling, multi-address failover stopping after
the first approved address, and missing bounded jitter. The first SNI integration run then
failed because the test backend returned a stream as response bytes; replacing it with a real
deterministic network-backend boundary made the test exercise httpcore's TLS/HTTP path.

### Exact green evidence

- Focused security/fetch/audit/migration command: `38 passed in 1.36s`.
- Full suite command: `308 passed in 6.28s`.
- Black: `19 files would be left unchanged`.
- Ruff: no findings.
- mypy: `Success: no issues found in 13 source files`.
- Git diff check: clean.

### Additional guarantees

- Positive request/attempt bounds are mandatory; attempts cap at three and decoded response
  bytes cap at 5 MiB even when hostile higher values are supplied.
- Public SafeFetcher construction has no client/transport parameter and always constructs the
  concrete `PinnedAsyncHTTPTransport`. Offline mocks use the explicitly private `_for_test`
  seam; passing `transport=` or an ordinary/malicious transport to public construction fails.
- The pinned backend tries every approved IPv4/IPv6 address within one remaining connect
  deadline and emits only a sanitized aggregate failure. A deterministic transport integration
  verifies the approved IP dial while preserving the original TLS SNI and HTTP Host header.
- Exponential retry delay has injectable jitter bounded to 25%/5 seconds and all Retry-After
  and computed delays remain capped at 15 minutes.
- Circuit eligibility commits read-only paths before network execution. True `asyncio.gather`
  two-session tests prove one winner for initial/stale source claims and half-open probes.
- `httpx==0.25.2` and `httpcore==1.0.9` are explicitly pinned in `pyproject.toml`; the existing
  lock already resolves exactly those versions. The transport integration test guards the
  unavoidable internal adapter boundary.

## Final HIGH remediation (2026-07-15)

### Exact red/green evidence

- Red regression command against the rejected constructor seam:
  `pytest tests/unit/test_retrieval_fetching.py::test_fetcher_rejects_unpinned_transport -q`
  produced `1 failed in 0.77s`; signature inspection found `_test_transport`.
- Green focused security/fetch/audit/migration command: `38 passed in 1.49s`.
- Green full suite: `308 passed in 6.43s`.
- Black: `17 files would be left unchanged`; Ruff clean; mypy clean across 13 source files;
  `git diff --check` clean.

### Final transport boundary

- SafeFetcher has no client, transport, backend, or factory argument and no `_for_test`
  classmethod. Both the old `transport=` and `_test_transport=` keywords raise `TypeError`.
- Every production SafeFetcher constructs `PinnedAsyncHTTPTransport`; `_attempt` calls its
  `approve()` unconditionally before the request. There is no duck-typed/no-op approval path.
- Offline response tests patch the already-owned client's response transport after construction,
  without changing the SafeFetcher production constructor. The security integration monkeypatches
  only concrete transport construction to supply a fake low-level backend, then drives a complete
  SafeFetcher request and proves the actual dial used the approved public IP while TLS SNI and the
  HTTP Host header retained the registry hostname.
