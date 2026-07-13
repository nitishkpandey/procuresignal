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

The cache repository's two-session concurrent writer behavior remains database-specific. Task 3 already uses a nested transaction plus unique-key recovery, and the complete suite is green, but a true PostgreSQL concurrency test belongs in the database integration environment rather than SQLite's locking model.
