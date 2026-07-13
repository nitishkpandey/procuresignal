# Phase 2: Cost-Optimized Enrichment Completion Report

## Outcome

Phase 2 is implemented and verified. Enrichment now uses one auditable cascade:
compatible cache, deterministic rules, bounded LLM fallback, skip, or defer. The
fixed 20-record evaluation avoids 12 of 15 otherwise accepted LLM calls (80%),
inside the required 70–85% range, while retaining 100% exact-set recall against
the recorded supplier, region, category, and signal baselines.

Cached and deterministic routes make no OpenAI call. Ambiguous relevant articles
can still use the existing `ArticleEnricher`, subject to hard per-run reservations.
Completed rows persist the route, reason, policy version, fingerprint,
deterministic confidence when computed, and whether an LLM was used.

## Measured Evaluation Evidence

The fixed offline fixture is executed through `EnrichmentPipeline` with SQLite,
the real deterministic analyzer/router/cache, and recorded offline LLM outputs;
it makes no network call. It contains 20 representative English, German, and French
records: clear and ambiguous procurement reporting, irrelevant content, exact and
near duplicates, entity-rich articles, and missing-description cases.

| Measure | Result |
| --- | ---: |
| Total fixture records | 20 |
| Accepted candidates | 15 |
| Rejected as irrelevant | 5 |
| Cached routes | 1 |
| Deterministic routes | 11 |
| LLM routes | 3 |
| Avoided accepted-candidate LLM calls | 12 |
| LLM-call avoidance | 80% |
| Supplier exact-set recall | 100% |
| Region exact-set recall | 100% |
| Category exact-set recall | 100% |
| Signal exact-set recall | 100% |

All extraction dimensions therefore have a zero percentage-point loss against
the fixture's recorded baseline, within the five-point maximum regression gate.
The three recorded LLM routes report 300 tokens total. Pipeline reservations use
the production character-based estimate and remain below the default limits of
five calls and 6,000 tokens.

## Policy, Budget, And Cache Behavior

The balanced default policy uses a 0.35 relevance threshold, 0.72 deterministic
confidence threshold, 0.50 failure-fallback confidence, five LLM calls, 6,000
estimated tokens, a 420-character extractive summary, policy version `cost-v1`,
and taxonomy version `signals-v1`.

Reservations are accepted only when both remaining call and estimated-token
capacity are available. An attempted failed call retains its reservation. Relevant
ambiguous work is deferred when capacity or an LLM client is unavailable, so it
remains eligible for a later run. Worker results expose cached, deterministic,
LLM, skipped, deferred, failed, cache-miss, call, token, and avoided-call metrics
while preserving the previous result keys.

Below-relevance decisions are terminal: the raw row is marked `skipped` in the
same transaction, and scheduled candidate selection excludes terminal and
already-processed rows before applying its batch cap. This prevents a newest-first
backlog of irrelevant rows from starving older eligible work. Deferred rows are
not marked and remain eligible. Successful LLM results are merged with explicit
deterministic supplier, region, and category evidence before caching or persistence.

Fingerprints normalize content deterministically and include policy and taxonomy
versions. Only validated deterministic or LLM outputs enter the persistent cache.
Corrupt or incompatible entries are misses. The integration test processes one
clear article and its cache-compatible duplicate in a single batch, then retries
that same batch. A forbidden lazy-client factory proves neither route constructs
an OpenAI client. The test proves deterministic and cached route counts of one,
zero LLM calls/tokens, two avoided calls, two saved rows on the first run, both
inputs already processed on retry, a cache hit count of one, complete audit
metadata, and no duplicate processed row.

## Database Migration

Alembic revision `f6a7b8_add_enrichment_routing_cache` adds processed-article
audit columns, the versioned enrichment cache, and one-processed-row-per-raw-row
uniqueness. Historical duplicates are ranked by completed status, populated audit
evidence, processing time, and ID. References from article matches, priority
events, user feeds, and risk events are repointed before duplicate deletion.
Revision `f7b8c9_terminal_enrichment` adds the indexed raw-article terminal status
used by scheduled candidate selection.

Fresh SQLite upgrade from an empty database completed through the new revision,
and `alembic heads` reported exactly one head:
`f7b8c9_terminal_enrichment`. The dedicated populated migration test also
proves dependent references survive upgrade and the migration can be downgraded.
PostgreSQL-dialect upgrade and downgrade SQL generation was verified earlier in
the phase; no disposable live PostgreSQL service was available for data-bearing
execution.

## Verification Record

Commands were run from the Phase 2 worktree using the repository's shared Python
environment.

- `PYTHONPATH=shared ../../.venv/bin/pytest tests/integration/test_api.py tests/unit/test_enrichment_pipeline.py tests/unit/test_enrichment_cache.py -v`
  — 51 passed.
- `DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase2-final-task6.db ../../.venv/bin/alembic upgrade head`
  — upgraded successfully to the Phase 2 revision.
- `../../.venv/bin/alembic heads` — exactly one head.
- `../../.venv/bin/black --check .` — 131 files unchanged after formatting the
  new integration test.
- `../../.venv/bin/ruff check .` — passed.
- `../../.venv/bin/mypy api worker shared` — no issues in 86 source files.
- `PYTHONPATH=shared ../../.venv/bin/pytest tests -q` — 240 passed.
- `npm run lint` — no ESLint warnings or errors.
- `npm run typecheck` — passed.
- `npm run test:run` — 52 tests passed across 16 files.
- `npm run build` — Next.js production build completed for all routes.
- `docker compose config --quiet` — passed.
- `git diff --check` — passed.

The isolated worktree does not contain ignored dependencies, so frontend checks
used a temporary ignored `node_modules` symlink to the main workspace's installed,
lockfile-compatible dependencies. An initial parallel typecheck raced with the
build's regeneration of `.next` and reported missing generated files; the same
typecheck passed after the build completed. Vitest printed Vite's CJS Node API
deprecation warning. The Next.js build printed Node experimental `localStorage`
warnings during static generation; neither warning affected the passing gates.

`docker compose config --quiet` validates Compose interpolation and configuration
only. It does not build images, start containers, test service health, or prove
runtime connectivity. No Compose image build was performed as part of this gate.

## Remaining Limitations

- Budget accounting is per process/run, not a distributed quota across workers.
- The token guard is based on a conservative character estimate; provider-reported
  actual usage is recorded but cannot be known before the request.
- Cache reuse is exact after normalization and versioning; semantic near-duplicate
  matching and embeddings remain outside Phase 2.
- Deterministic language, entity, and signal coverage is bounded by the maintained
  rule taxonomy; broader accuracy measurement belongs to Phase 5.
- A live PostgreSQL migration rehearsal with production-scale representative data,
  backup, lock-duration observation, and rollback rehearsal remains required before
  production deployment.
- Compose services and images still require separate build and runtime verification
  in the production-readiness phase.

`docs/interview-preparation.md` was intentionally left unchanged. Its update
remains deferred until Phase 10.
