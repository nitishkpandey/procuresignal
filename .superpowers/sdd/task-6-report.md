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

## Independent review fixes

Addressed all four review findings without enabling or implementing structured sanctions:

- `RSSProvider` now raises a structured `RetrievalFetchError` for every failed `FetchResult`; the orchestrator preserves the exact failure enum, decoded response-byte count, and durable circuit state.
- `FetchResult.response_bytes` is populated by `SafeFetcher` from decoded streamed bytes, including the over-limit byte count. Article JSON serialization is no longer used as a transport-byte proxy.
- RSS accepts the injected orchestration registry version, and legacy articles receive registry provenance before persistence.
- `configured_registry()` adds NewsAPI when `NEWSAPI_KEY` exists and GDELT only when `GDELT_ENABLED=true`, using the providers' existing endpoint constants and validated `SourceDefinition` objects. The worker passes this registry into the same orchestrator path.
- Provider construction is inside the source failure boundary; close is attempted exactly once only for constructed providers and isolated from durable source/run finalization.

### Review-fix red/green evidence

- Red: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py tests/unit/test_rss_contracts.py tests/unit/test_retrieval_fetching.py tests/unit/test_tasks.py -k 'retrieval or provider or rss or fetch' -v`
  - 33 passed, 1 failed. The lifecycle regression initially assumed insertion order despite the registry's specified source-ID ordering; corrected to assert the source/status mapping. The new production RSS failure, legacy registry configuration, and lifecycle behavior otherwise executed.
- Green: same focused behavior command after correction was covered by the final suite below.
- Green: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_rss_contracts.py tests/unit/test_tasks.py tests/integration/test_api.py -v`
  - Exit 0: 115 passed.
- Static: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/orchestrator.py shared/procuresignal/retrieval/persistence.py shared/procuresignal/retrieval/providers/rss.py worker/tasks.py`
  - Exit 0: success, no issues in 4 source files.
- Static cleanup: initial Ruff run found one import-order issue after the review patch; `ruff check --fix` corrected it.
- Final static: `../../.venv/bin/ruff check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py; git diff --check`
  - Exit 0 with no findings.

### Review-fix self-review

- Structured fetch failures never include URLs, bodies, tokens, or exception strings in returned/persisted outcomes.
- Open-circuit state comes from `NewsRetrievalCircuit`, not a constant result default.
- Close failures cannot replace an already durable success or escape `gather`; constructor failures become durable parser-failure outcomes and the run still completes.
- NewsAPI/GDELT are registry entries feeding the same claim/concurrency/persistence path. No second worker loop was restored.
- Known provider endpoint constants were reused; no new endpoint was invented and `SourceRegistry` validation remains unchanged.

## Second review wave: mandatory SafeFetcher for legacy adapters

- Extended `SafeFetcher.fetch()` with typed in-memory query parameters. Parameters are applied only to the initial approved HTTPS request and are removed on redirects, so a NewsAPI key cannot cross a redirect boundary.
- Registry definitions remain secret-free. `NEWSAPI_KEY` is injected only into the `params` mapping passed directly to the safe transport; it is absent from source URLs, audit rows, result URLs, exception messages, and logs.
- Orchestrator-created NewsAPI and GDELT providers now receive `SafeFetcher`; their injected mode does not construct or call the generic `NewsProvider` client.
- Both adapters translate failed `FetchResult` values into `RetrievalFetchError`, accumulate decoded response bytes across successful pages and the terminal failure, and re-raise structured failures rather than silently reporting a partial success.
- This preserves the one orchestrator path and inherits the reviewed DNS pinning, allowed-host/HTTPS validation, response cap, redirect cap, timeouts, retry, and durable circuit behavior.

### Second-wave evidence

- Focused provider/orchestrator/worker command: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_retrieval_fetching.py tests/unit/test_tasks.py -v`
  - Exit 0: 49 passed. New regressions verify decoded byte accumulation, structured open-circuit failure, secret-free URLs, parameter-only API-key injection, and that no generic client request occurs for NewsAPI/GDELT injected adapters.
- Full focused Task 6 command: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_rss_contracts.py tests/unit/test_tasks.py tests/integration/test_api.py -v`
  - Exit 0: 118 passed.
- First second-wave static run was red: Ruff found two import-order errors and MyPy found three annotations/query-parameter typing errors. These were corrected without behavior changes.
- Final static: `../../.venv/bin/ruff check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py`
  - Exit 0, no findings.
- Final types: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/orchestrator.py shared/procuresignal/retrieval/fetching.py shared/procuresignal/retrieval/providers/newsapi.py shared/procuresignal/retrieval/providers/gdelt.py shared/procuresignal/retrieval/providers/rss.py worker/tasks.py`
  - Exit 0: success, no issues in 6 source files.
- `git diff --check`
  - Exit 0.

No commit was attempted for this fix wave because the controller explicitly requested that sandbox-blocked git metadata operations be left to the controller.

## Final malformed-response fix

NewsAPI and GDELT JSON decoding failures now become `RetrievalFetchError` instances carrying `FetchFailureCode.PARSER_ERROR` and the authoritative accumulated decoded byte count. Existing provider loops explicitly re-raise this structured exception, so malformed responses cannot become empty or partial successes. The orchestrator durably records the source failure and aggregates the parser rejection without persisting exception text or response content.

### Red/green evidence

- Red: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k malformed -v`
  - Exit 1: 2 failed. Both NewsAPI and GDELT malformed-response cases returned no rejection because their generic provider exception handlers converted JSON decoding errors into empty success.
- Green: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval.py tests/unit/test_retrieval_orchestrator.py -v`
  - Exit 0: 16 passed, including both adapter-specific malformed production-response regressions.
- Ruff: `../../.venv/bin/ruff check shared/procuresignal/retrieval/providers shared/procuresignal/retrieval/orchestrator.py tests/unit/test_retrieval_orchestrator.py`
  - Exit 0, no findings.
- MyPy: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/providers/newsapi.py shared/procuresignal/retrieval/providers/gdelt.py shared/procuresignal/retrieval/orchestrator.py`
  - Exit 0: success, no issues in 3 source files.
- `git diff --check`
  - Exit 0.

The regressions assert failed source status, `parser_error`, decoded bytes, zero inserts, and absence of malformed body content from the run result representation. No commit was attempted, per controller instruction.

## Final circuit ownership fix

Circuit-success reset is now deferred for orchestrator-owned `SafeFetcher` instances until the provider has fully parsed every response. SafeFetcher continues to own and count transport failures. The orchestrator adds exactly one circuit failure only for `PARSER_ERROR`, then completes the durable source failure. A fully parsed success resets the circuit at the source boundary, including a claimed half-open probe.

### Red/green evidence

- Red: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k parser_failures -v`
  - Exit 1: the new five-failure regression found no circuit row, proving parser failures were not counted.
- Green: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k 'parser_failures or malformed' -v`
  - Exit 0: 3 passed, 9 deselected. Five consecutive parser failures open the durable circuit; a later half-open parsed success resets failure count and cooldown.
- Full focused Task 6: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_rss_contracts.py tests/unit/test_tasks.py tests/integration/test_api.py -v`
  - Exit 0: 121 passed.
- Ruff: `../../.venv/bin/ruff check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py`
  - Exit 0, no findings.
- MyPy: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/orchestrator.py shared/procuresignal/retrieval/fetching.py shared/procuresignal/retrieval/providers/newsapi.py shared/procuresignal/retrieval/providers/gdelt.py shared/procuresignal/retrieval/providers/rss.py worker/tasks.py`
  - Exit 0: success, no issues in 6 source files.
- `git diff --check`
  - Exit 0.

Transport failure codes are not incremented by the orchestrator, preventing double-counting. No commit was attempted, per controller instruction.

## Half-open multi-request probe ownership

`allow_circuit_request` now permits the current, unexpired `probe_owner` to continue a bounded multi-request source run. Other owners remain denied, and the existing expiry condition still permits one later atomic reclaim. SafeFetcher now uses the repository-compatible naive UTC clock by default, avoiding aware/naive comparisons against the database's timestamp-without-time-zone circuit columns.

### Red/green evidence

- Red: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k half_open_owner -v`
  - Exit 1. The real NewsAPI/SafeFetcher recovery exercised the durable circuit and first exposed the production clock mismatch; after clock normalization it exposed the same-owner continuation denial targeted by this fix.
- Green targeted: same command after the ownership change.
  - Exit 0: 1 passed, 12 deselected. The claimed owner completed the initial probe plus all six NewsAPI requests, a different owner was denied without issuing a request, and the parsed success closed the circuit.
- Circuit/concurrency coverage: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_audit.py tests/unit/test_retrieval_fetching.py tests/unit/test_retrieval_orchestrator.py -v`
  - Exit 0: 42 passed.
- Full focused Task 6: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_rss_contracts.py tests/unit/test_tasks.py tests/integration/test_api.py -q`
  - Exit 0: 122 passed.
- MyPy: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval/orchestrator.py shared/procuresignal/retrieval/audit.py shared/procuresignal/retrieval/fetching.py shared/procuresignal/retrieval/providers/newsapi.py shared/procuresignal/retrieval/providers/gdelt.py shared/procuresignal/retrieval/providers/rss.py worker/tasks.py`
  - Exit 0: success, no issues in 7 source files.
- Ruff initially found one import-order issue in the new test, fixed mechanically. Final Ruff and `git diff --check` both exit 0.

No commit was attempted, per controller instruction.

## Retry aggregation and renewal TOCTOU fix

Same-owner retries now reconstruct terminal source results from durable `NewsRetrievalSourceOutcome` rows when a source claim is no longer available. Current-attempt and prior-attempt outcomes therefore appear exactly once in provider results and final run totals. A retry after every source completed can finalize the run from prior durable totals without refetching. Stored combined duplicate counts are conservatively surfaced as database duplicates because the audit schema does not persist the within-run/database split; response-byte metrics likewise remain available only for the active invocation because no durable byte column exists.

Run/source same-owner renewals now use ownership/status-guarded updates and require `rowcount == 1`. A concurrent completion/theft cannot return acquired/proceed. The failed run-renewal branch refreshes ORM state before classifying the result.

### Evidence

- Targeted retry regressions: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k 'retry_aggregates or all_sources_complete or retry_owner' -v`
  - Exit 0: 3 passed, 16 deselected. Attempt A + retry B totals are included once; an all-sources-complete retry finalizes prior totals and never constructs a provider.
- Focused audit/orchestrator/worker: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_audit.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py -q`
  - Exit 0: 43 passed.
- Full backend unit + API integration: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit tests/integration/test_api.py -q`
  - Exit 0: 335 passed.
- Ruff exited 0 with no findings.
- Black exited 0 with 20 files unchanged.
- MyPy exited 0 with no issues in 16 source files.
- `git diff --check` exited 0.

No commit was attempted, per controller instruction.

## Final whole-branch review fixes

### Lease fencing and atomic persistence

- `ArticlePersistence.save_articles(..., commit=False)` keeps raw inserts in the caller's transaction.
- The orchestrator fences the active run with an ownership/expiry-guarded write before persistence, then performs inserts and the guarded source completion in the same transaction. A failed run or source fence rolls back all candidate rows and returns `lease_lost`; it does not reset the circuit or report completion.
- Circuit success is recorded only after the source transaction commits under a valid fence.
- A rejected final `complete_run` returns a run-level `lease_lost` result with an explicit rejection instead of `completed`.

### Retry ownership and takeover accounting

- `RetrievalOrchestrator` accepts an explicit owner token. The Celery retrieval task supplies its stable task ID, which Celery preserves across retries.
- A retry with the same owner resumes its live run/source leases; a different owner remains `already_running` until expiry or hard-death reclaim.
- Expired run and source takeovers atomically increment `attempted_count`; new source claims start at one.

### Red/green evidence

- Red lease theft: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_orchestrator.py -k lease_theft -v`
  - Exit 1: 2 failed because rows inserted inside implicit SQLite savepoints survived the later fence rollback. Moving the guarded run write before savepoints established the outer write transaction and made rollback effective.
- Green lease theft: same command after the transaction-boundary correction.
  - Exit 0: 2 passed, 13 deselected. Both source-owner theft and run-owner theft return `lease_lost`, report zero inserts, and leave no raw rows.
- Initial covering run exposed three test/implementation issues: missing run takeover increment, an unconditional write-based same-owner source check causing SQLite lock contention, and a race assertion that excluded the honest `already_completed` result. Run takeover now increments atomically; source resume first verifies matching live ownership before atomically renewing its lease/attempt count; the race contract accepts either running or completed observation while requiring exactly one completed execution.
- Green covering audit/orchestrator/worker: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit/test_retrieval_audit.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py -q`
  - Exit 0: 41 passed.
- Full backend unit plus API integration: `PYTHONPATH=shared ../../.venv/bin/pytest tests/unit tests/integration/test_api.py -q`
  - Exit 0: 333 passed.
- Ruff: `../../.venv/bin/ruff check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_audit.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py`
  - Exit 0, no findings.
- Black: `../../.venv/bin/black --check shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_audit.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py`
  - Exit 0: 20 files unchanged.
- MyPy: `PYTHONPATH=shared ../../.venv/bin/mypy shared/procuresignal/retrieval worker/tasks.py`
  - Exit 0: success, no issues in 16 source files.
- `git diff --check`
  - Exit 0.

No commit was attempted, per controller instruction.
