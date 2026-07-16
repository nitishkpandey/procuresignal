# Task 7 Report: Coverage Evaluation and Phase Documentation

## Status

Task 7 wiring, deterministic coverage evaluation, configuration documentation, Compose
propagation, and the Phase 3 source report are implemented. Production coverage honestly retains
`missing_structured_authoritative_domains == (sanctions,)`: the verified DG FISMA distribution
requires secret query injection and its 24,730,335-byte body exceeds the reviewed 5 MiB ceiling.
No security boundary was weakened and no sanctions fixture or coverage claim was fabricated.

One repository-wide formatting gate remains red on the pre-existing committed file
`tests/unit/test_models.py`. It was not changed because this task is restricted to Task 7 wiring,
docs, configuration, and report files. All changed Python files pass Black, Ruff, and MyPy, and
the complete backend and frontend suites pass.

## TDD evidence

### Coverage result metrics and zero-LLM wiring

1. Red: `PYTHONPATH=shared ../../.venv/bin/pytest tests/integration/test_retrieval_coverage.py -v`
   - Exit 1 with `AttributeError: 'RetrievalRunResult' object has no attribute 'llm_calls'`.
   - This demonstrated the missing additive retrieval-only metrics contract.
2. Green after the minimal result properties:
   - Exit 0, `1 passed`.

### Per-source configuration overrides

1. Red: the expanded focused command above collected two tests and failed
   `test_per_source_enable_overrides_are_explicit`; `eurostat_updates` remained enabled despite
   `SOURCE_EUROSTAT_UPDATES_ENABLED=false`.
2. Green after strict `SOURCE_<SOURCE_ID>_ENABLED=true|false` application:
   - Exit 0, `2 passed`.
3. A temporary exact-metric assertion intentionally failed with the observed tuple `(8, 8, 0)`
   instead of the guessed `(10, 6, 4)`. The fixture provider was then made to repeat one real
   parsed article so the end-to-end gate genuinely exercises in-run deduplication. The final exact
   metrics are asserted, not inferred.
4. Fresh final focused run after Ruff/Black cleanup:
   `PYTHONPATH=shared ../../.venv/bin/pytest tests/integration/test_retrieval_coverage.py -v`
   - Exit 0, `2 passed in 1.26s`.

## Fixture inventory and representative metrics

All recorded retrieval XML fixtures are exercised through the real RSS/Atom parser and real
orchestrator with a mocked fetch boundary:

- `ecb_press.xml`
- `eu_commission_press.xml`
- `europe_commodities.xml`
- `europe_logistics.xml`

The run uses the seven default-enabled `sources-v1` entries. Six complete and one returns a
structured `http_status` failure. It fetches 9 records, accepts/inserts 8, removes 1 within-run
duplicate, and observes 0 database duplicates. The same run key is replayed and inserts 0 rows.
Every persisted row has `source_id` and `registry_version`. OpenAI constructors imported by the
enricher, pipeline, client module, API translation boundary, and worker task boundary are patched
to raise; `result.llm_calls == 0` is asserted.

## Documentation and configuration

- README documents `sources-v1`, strict source toggles, GDELT opt-in, fixed safe-fetch ceilings,
  offline fixtures, and the structured-sanctions exception.
- `.env.example` lists each production source override and defaults GDELT to false.
- Compose explicitly passes GDELT and all source overrides to API, worker, and bootstrap runtime
  environments.
- The Phase report contains the enabled authority/domain/language matrix, endpoint review dates,
  rejected candidates and reasons, fixture inventory and metrics, claim/concurrency evidence,
  zero-LLM guarantee, migrations/compatibility, limitations, and rollout steps.
- `docs/interview-preparation.md` has no diff.

## Verification evidence

### Backend

- `PYTHONPATH=shared ../../.venv/bin/pytest tests -q`
  - Initial exit 0: `345 passed in 8.72s`.
  - Final fresh post-format/static run: exit 0, `345 passed in 7.29s`.
- `../../.venv/bin/ruff check .`
  - Initial exit 1 found three Task 7 import/unused-import findings; `ruff check --fix` corrected
    them mechanically.
  - Final exit 0.
- `PYTHONPATH=shared ../../.venv/bin/mypy api worker shared`
  - Exit 0: `Success: no issues found in 94 source files`.
- `../../.venv/bin/black --check .`
  - Exit 1: only `tests/unit/test_models.py` would be reformatted. This file has no Task 7 diff.
- `../../.venv/bin/black --check tests/integration/test_retrieval_coverage.py shared/procuresignal/retrieval/orchestrator.py`
  - Exit 0: both files would be left unchanged.

### Migrations

- `test ! -e /tmp/procuresignal-phase3-task7.db && DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase3-task7.db ../../.venv/bin/alembic upgrade head && ../../.venv/bin/alembic heads`
  - Exit 0; fresh upgrade reached `f8c9d0_add_retrieval_source_audit (head)` and exactly one head
    was printed.
- Inserted a populated legacy-compatible raw article with `sqlite3`, then ran
  `DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase3-task7.db ../../.venv/bin/alembic downgrade f7b8c9_terminal_enrichment`.
  - Exit 0; the populated row remained (`task7-populated|Task 7 migration fixture`).
- Re-upgraded the populated database to head.
  - Exit 0; the row remained and newly additive provenance columns were null, as expected for a
    row passing through downgrade/re-upgrade.
- The full backend run also passed the populated migration integration test.

### Frontend

- First `npm run lint` exited 127 because this worktree had no `node_modules` (`next: command not
  found`). `npm ci` then exited 0 and installed 533 locked packages.
- `npm run lint && npm run typecheck && npm run test:run && npm run build`
  - Exit 0: no ESLint findings; typecheck clean; 16 test files / 52 tests passed; production build
    compiled and generated all routes. Next emitted non-fatal Node experimental localStorage
    warnings during static generation.

### Compose, whitespace, and stale markers

- `docker compose config --quiet && git diff --check`
  - Exit 0.
- `rg -n "RSSProvider\.FEEDS|feeds\.reuters\.com|TBD|TODO|FIXME" shared worker tests README.md .env.example docs/superpowers/reports/2026-07-13-authoritative-procurement-sources.md`
  - Exit 1 with no output, meaning no stale references or incomplete markers were found in scope.

## Existing concurrency and compatibility evidence exercised by the full suite

Task 6's run/source race regressions prove exactly one worker owns a concurrent run/source claim,
stale leases are recoverable, global concurrency is at most six, per-host concurrency is at most
two, and source failures remain isolated. The Task 7 integration gate persists through the same
orchestrator and model path. Public API/frontend schemas are unchanged; the result counters are
additive internal properties.

## Concerns and limitations

- Structured authoritative sanctions data remains unavailable by design until a separately
  security-reviewed source-scoped streaming path and secret-backed query injection exist.
- CI is offline and does not prove future endpoint availability, terms stability, or payload
  compatibility; operators must reverify before enabling disabled sources.
- The literal brief path `.venv/bin/...` is absent inside this worktree. Commands used the shared
  repository environment at `../../.venv`.
- The earlier Phase 3 `tests/unit/test_models.py` formatting defect was corrected mechanically;
  the final repository-wide Black check passed with 150 files unchanged.
- `npm ci` reported upstream package deprecation warnings and three install scripts pending npm's
  allow-scripts review; installation and all requested frontend gates nevertheless exited 0.
