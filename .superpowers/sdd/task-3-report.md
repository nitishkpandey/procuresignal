# Task 3 Report: Auditable Models, Migration, and Persistent Cache

## Result

Implemented backward-compatible enrichment audit metadata, a versioned cache ORM model,
a reversible Alembic migration, and a validated async cache repository.

## Implementation

- Added nullable audit columns to `NewsArticleProcessed` and non-null `llm_used` with
  Python and server defaults of false so historical rows are backfilled safely.
- Added `EnrichmentCacheEntry`, exported from the model package, with JSON payload,
  timestamps, hit count, method check constraint, fingerprint lookup index, and unique
  `(content_fingerprint, policy_version, taxonomy_version)` identity.
- Added `EnrichmentCache.get()` and `put()` without independent commits. Reads validate
  payloads before atomically incrementing hit count. Corrupt payloads log a warning and
  return a miss without incrementing. Writes validate the original method and handle a
  concurrent unique-key insert through a savepoint and update fallback.
- Added reversible migration `f6a7b8_add_enrichment_routing_cache` on the current
  `e5f6a7_add_risk_event_scan_tracking` head.
- Made the pre-existing migration chain SQLite-compatible while preserving PostgreSQL
  types and behavior: SQLite JSON variants replace unsupported ARRAY/JSONB during the
  historical migration, PostgreSQL-only type conversion is skipped on SQLite, and
  SQLite retains the safe `platform_language` server default because it cannot drop a
  column default in place. Alembic only appends the asyncpg SSL query parameter to
  PostgreSQL URLs.

## TDD and Verification

- RED: focused tests failed during collection with missing
  `procuresignal.enrichment.cache`.
- GREEN: focused model/cache suite: 14 passed.
- Full unit suite: 173 passed.
- Fresh SQLite migration: upgraded base through head and downgraded Task 3 to
  `e5f6a7_add_risk_event_scan_tracking`.
- Alembic reports exactly one head: `f6a7b8_add_enrichment_routing_cache`.
- Ruff passes for all changed Python files.
- MyPy passes for the model package and cache repository.
- `git diff --check` passes.

## Review Notes

- Cache hit increments use one database-side arithmetic update to prevent lost updates
  across concurrent readers.
- The unique constraint is the final concurrency guard for writers; `put()` uses a
  nested transaction so a competing insert does not roll back the pipeline transaction.
- PostgreSQL migration execution was not available locally; PostgreSQL-specific behavior
  was retained rather than replaced, while the required SQLite migration gate was run.
