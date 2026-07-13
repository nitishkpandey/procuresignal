# Phase 2 Task 4: Cost-Aware Cascade Integration

## Status

DONE. `EnrichmentPipeline` is now the single transaction owner and routes every new candidate to exactly one of cached, deterministic, LLM, skipped, deferred, or failed. Existing worker tuple unpacking remains compatible through `EnrichmentRunResult.__iter__` while the richer metrics contract is available to later task wiring.

## Implementation

- Added dependency injection for policy, router, deterministic enricher, persistent cache, and optional LLM client.
- Added `EnrichmentMetrics` and `EnrichmentRunResult`, with separate `already_processed` semantics.
- Added lazy LLM capability: constructing a pipeline without an OpenAI client still supports cache, deterministic, skipped, and deferred routes.
- Split `ArticleEnricher.generate_output()` from the compatibility `enrich()` model-conversion wrapper; no second OpenAI caller exists.
- Added stable fingerprint/cache lookup, hard budget reservation, token accounting, validated fallback, audit metadata, cache writes, and one batch commit/rollback boundary.
- Deferred and skipped candidates do not create completed processed rows. Already-processed raw IDs do not increment skipped or any terminal route counter.
- Cache and deterministic paths make zero OpenAI calls. Failed attempted calls retain their budget reservation.

## Verification

```text
PYTHONPATH=shared .../.venv/bin/pytest tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py -q
16 passed

PYTHONPATH=shared .../.venv/bin/pytest tests -q
216 passed

.../.venv/bin/ruff check shared/procuresignal/enrichment tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py
passed

.../.venv/bin/mypy shared/procuresignal/enrichment
Success: no issues found in 12 source files

git diff --check
passed
```

Focused Black formatting passes for the Task 4 modified Python files. A directory-wide Black check also identifies pre-existing formatting drift in Task 1's `policy.py` and `router.py`; those files were not modified here to avoid crossing task ownership.

## Tests Added

- deterministic then persistent-cache reuse, both with zero LLM calls;
- ambiguous relevant article uses exactly one LLM call;
- reprocessing a completed raw ID creates no duplicate and reports `already_processed` separately;
- exhausted token budget defers without inserting a processed row;
- every candidate increments exactly one terminal route counter.

## Concerns

SQLite and PostgreSQL have different locking behavior, so the two-session test proves durable uniqueness and usable savepoint recovery but is not a substitute for a live PostgreSQL race test.

## Review Follow-up

Commit follow-up adds the explicit `min_fallback_confidence` policy (default 0.50), cache-hit short-circuiting before deterministic work, processed raw-ID uniqueness at ORM/migration/runtime boundaries, historical duplicate cleanup in the migration, and savepoint recovery for concurrent unique violations. It also adds exception fallback above/below threshold, analyzer-spy cache, corrupt-cache continuation, optional-client, batch rollback, same-input duplication, audit metadata, model uniqueness, and two-session durability tests.

Fresh evidence after the follow-up:

```text
focused policy/cache/pipeline/model suite: 60 passed
full backend suite: 228 passed
repository Ruff: passed
MyPy api worker shared: Success, 86 source files
Black modified scope: passed after formatting
PostgreSQL offline Alembic upgrade e5f6a7...:f6a7b8...: generated successfully
PostgreSQL offline Alembic downgrade f6a7b8...:e5f6a7...: generated successfully
```

The Alembic validation was PostgreSQL-dialect offline SQL generation because no disposable live PostgreSQL database was available in the task environment. It validates upgrade/downgrade DDL generation, not execution against production data.

## Migration Data-Safety Follow-up

The migration now adds nullable audit columns first, ranks duplicate processed rows deliberately, and selects the survivor by this stable order: completed status, greatest non-null enrichment/audit evidence, newest `processed_at`, then greatest ID. A temporary old-ID to survivor-ID map repoints `news_article_matches`, `news_priority_events`, `user_news_feed`, and `risk_events` before duplicate processed rows are deleted.

Schema inspection confirms that at revision `e5f6a7_add_risk_event_scan_tracking`, none of those dependent tables has a unique constraint involving `processed_article_id`. Consequently remapping cannot cause a unique-key collision. Every dependent row is retained, which preserves matching evidence, priority dispatch state, feed read/hidden state, and independently keyed risk events. The only relevant dependent uniqueness is `risk_events.event_key`, which is unchanged by remapping.

Fresh populated migration evidence:

```text
tests/integration/test_enrichment_migration.py: 1 passed
full backend suite: 229 passed
repository Ruff: passed
MyPy api worker shared: Success, 86 source files
PostgreSQL offline upgrade and downgrade SQL: generated successfully
```

The populated SQLite test constructs the prior-revision processed/dependent schema, inserts three processed duplicates plus references from all four dependent tables, includes multiple dependent rows that converge on the survivor, and proves: the completed/richer/newer row survives; every reference is repointed; no dependent row is lost or left dangling; one processed row remains per raw ID; the new uniqueness constraint rejects another duplicate; and downgrade removes the new cache/audit/constraint structures. SQLite execution plus PostgreSQL offline SQL generation cover both migration branches; a production-data backup and dry run remain required before deployment.
