# Phase 2: Cost-Optimized Enrichment Design

## Objective

Reduce paid LLM enrichment calls by 70–85% on a representative fixed evaluation fixture without materially reducing supplier, region, category, or procurement-signal extraction coverage. Keep routing explainable, enforce hard budgets, preserve idempotency, and retain LLM enrichment for ambiguous high-value articles.

## Selected Approach

Use a deterministic enrichment cascade before OpenAI:

1. Reject content that fails existing quality or procurement-relevance requirements.
2. Skip raw articles that already have a processed result.
3. Compute a stable normalized-content fingerprint and check the versioned enrichment cache.
4. Extract categories, signals, suppliers, regions, and other metadata with existing deterministic taxonomies and entity rules.
5. Calculate deterministic confidence and procurement relevance.
6. Route the article to deterministic enrichment, cached enrichment, LLM enrichment, skip, or defer.

Embedding-first routing and batch LLM requests are excluded from Phase 2. Phase 5 evaluation data will determine whether embeddings justify their additional cost and operational complexity.

## Architecture

### Enrichment Router

`EnrichmentRouter` owns routing decisions. It consumes a normalized `RawArticle`, current policy, cache result, deterministic analysis, and remaining budget. It returns an explicit route, reason, confidence, and the information required by the selected enricher. It does not persist data or call external APIs.

Supported routes:

- `cached`: reuse a compatible prior enrichment.
- `deterministic`: create a processed article entirely from local rules.
- `llm`: use OpenAI for relevant articles whose deterministic result is ambiguous.
- `skipped`: reject irrelevant or insufficient-quality content.
- `deferred`: retain a relevant article for a later run when the LLM budget is exhausted and deterministic confidence is insufficient.

### Deterministic Enricher

`DeterministicEnricher` produces a complete processed-article payload without an LLM. It reuses the existing signal taxonomy, supplier and region extraction, category aliases, source metadata, and normalized article text. Its summary is extractive and bounded: prefer the normalized description, then the content snippet, then the title, with deterministic truncation.

### Enrichment Cache

`EnrichmentCache` persists reusable enrichment payloads in PostgreSQL. A cache key combines:

- Normalized title, description, and content snippet.
- Article language.
- Enrichment policy/version identifier.
- Deterministic taxonomy/version identifier.

Cache entries store only successful, validated payloads. Failures, malformed LLM results, skipped articles, and deferred articles are never cached. Versioned fingerprints prevent old rules or prompt formats from being reused after policy changes.

### Enrichment Policy And Budget

`EnrichmentPolicy` is immutable configuration resolved at the start of each run. It contains:

- Minimum procurement-relevance score.
- Minimum deterministic confidence.
- Maximum LLM calls per run.
- Maximum estimated input/output tokens per run.
- Extractive summary length.
- Cache and policy versions.

Environment variables may override safe defaults. Invalid values fail fast at configuration loading rather than silently disabling limits.

`EnrichmentBudget` tracks reserved and consumed calls/tokens within one run. A reservation must succeed before an LLM call begins. Failed calls consume their attempted call reservation so repeated failures cannot bypass the cap.

### Metrics

`EnrichmentMetrics` records totals for cached, deterministic, LLM, skipped, deferred, failed, cache misses, LLM calls, input/output tokens, and estimated avoided calls. Worker task results expose these counters for logs and future observability without changing current API contracts.

## Data Model

Extend processed articles with auditable routing metadata:

- `enrichment_method`: `cached`, `deterministic`, or `llm` for completed records.
- `enrichment_reason`: stable machine-readable routing reason.
- `enrichment_policy_version`: version used for the decision.
- `content_fingerprint`: normalized versioned fingerprint.
- `deterministic_confidence`: numeric score from 0 to 1.
- `llm_used`: boolean.

Create an `enrichment_cache` table containing fingerprint/version uniqueness, validated enrichment payload, original method, timestamps, and hit count. Add a unique constraint on the compatible cache identity and an index supporting lookup.

Skipped and deferred outcomes are recorded as processing state on the raw/pipeline tracking boundary rather than inserted as completed processed articles. A deferred article remains eligible in a later scheduled run.

All schema changes use an Alembic migration and preserve existing rows with explicit backward-compatible defaults or nullable audit fields.

## Data Flow

The worker loads normalized candidates and excludes already processed raw IDs. For each candidate:

1. Build normalized text and a versioned fingerprint.
2. Query the cache.
3. If a compatible cache hit exists, validate and persist the cached result.
4. Otherwise perform deterministic analysis and score relevance/confidence.
5. Skip articles below minimum relevance.
6. Persist deterministic results at or above the confidence threshold.
7. For relevant ambiguous articles, reserve budget and call the existing `ArticleEnricher`.
8. If no budget is available, mark the outcome deferred without losing eligibility.
9. If OpenAI fails or returns malformed output, persist deterministic fallback only when it meets the minimum fallback confidence; otherwise defer or record failure explicitly.
10. Cache only validated completed payloads and expose routing metrics.

The existing `ArticleEnricher` remains the only LLM enrichment implementation. OpenAI access does not spread into router, cache, policy, or deterministic components.

## Error Handling And Safety

- Database uniqueness and idempotent checks prevent duplicate processed rows during retries or concurrent workers.
- Cache payloads are validated through the same structured output model used by fresh enrichment.
- Corrupt or incompatible cache entries are treated as misses and logged; they do not break the batch.
- OpenAI errors do not silently discard relevant articles.
- Budget exhaustion produces a distinct deferred outcome.
- Failures are not cached.
- Policy and taxonomy changes invalidate reuse through versioned fingerprints.
- Metrics count each candidate in exactly one terminal route per run.
- No LLM call occurs before relevance, cache, deterministic, and budget checks complete.

## Testing And Evaluation

Unit tests cover:

- Canonical content fingerprints and version invalidation.
- Policy parsing and invalid configuration.
- Every routing decision and stable reason.
- Confidence/relevance thresholds at their boundaries.
- Extractive deterministic summaries and entity merging.
- Budget reservation, exhaustion, and failed-call accounting.
- Cache validation, hit counting, miss behavior, and corrupt payload handling.

Integration tests prove:

- Cached and deterministic routes make zero OpenAI calls.
- Ambiguous high-value articles use OpenAI when budget exists.
- Budget exhaustion defers rather than loses work.
- OpenAI failure follows the confidence-based fallback path.
- Repeated and concurrent processing remains idempotent.
- Migrations upgrade and downgrade cleanly for the new structures.

A fixed representative fixture contains relevant, irrelevant, clear, ambiguous, duplicate, multilingual, and entity-rich articles. The evaluation reports:

- LLM-call avoidance rate among accepted candidates.
- Supplier, region, category, and signal coverage versus the current LLM baseline.
- Cache-hit and deterministic-route proportions.
- Deferred, skipped, and failure counts.

Acceptance requires 70–85% LLM-call avoidance without material extraction-coverage regression. For this phase, "material" means no evaluated dimension decreases by more than five percentage points from the recorded baseline. Existing backend and frontend quality gates must remain green.

## Scope Boundaries

Phase 2 includes deterministic routing, cache reuse, hard per-run budgets, audit metadata, metrics, evaluation fixtures, and migration work required by those capabilities.

Phase 2 excludes embeddings, vector databases, learning-to-rank, new external news sources, preference-ranking changes, autonomous procurement agents, authentication, UI dashboards, and notifications. Those remain in their assigned later phases.

## Success Criteria

- The deterministic cascade is the single entry point for article enrichment.
- Cached and deterministic routes perform no OpenAI calls.
- Ambiguous relevant articles can still use OpenAI within budget.
- LLM calls and tokens cannot exceed configured per-run limits.
- Relevant budget-blocked articles remain eligible for later processing.
- Every completed article exposes auditable enrichment metadata.
- Cache reuse is versioned, validated, and persistent across workers.
- The fixed evaluation fixture demonstrates 70–85% call avoidance with no extraction dimension losing more than five percentage points.
- All migrations, backend tests, frontend tests, lint, formatting, type checks, and production build pass.
