# Phase 2 Cost-Optimized Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route 70–85% of accepted evaluation articles away from OpenAI through deterministic enrichment and persistent versioned cache reuse while preserving extraction coverage within five percentage points of baseline.

**Architecture:** Introduce pure policy, fingerprint, budget, deterministic-analysis, and routing units before persistence. Add auditable processed-article metadata plus a PostgreSQL cache, then make `EnrichmentPipeline` the single orchestration boundary that selects cached, deterministic, LLM, skipped, or deferred outcomes and emits route metrics.

**Tech Stack:** Python 3.11, Pydantic 2, SQLAlchemy 2 async ORM, Alembic, PostgreSQL/SQLite tests, FastAPI, Celery, OpenAI Responses API, Pytest, Black, Ruff, MyPy.

## Global Constraints

- Avoid 70–85% of LLM calls on the fixed representative fixture.
- No supplier, region, category, or signal extraction dimension may lose more than five percentage points versus the recorded LLM baseline.
- Cached and deterministic routes must make zero OpenAI calls.
- Per-run call and token limits are hard caps; failed attempted calls consume their reservation.
- Relevant budget-blocked work remains eligible for a later run.
- Cache only validated successful payloads and invalidate reuse by policy/taxonomy version.
- Preserve existing API contracts and frontend behavior.
- Do not introduce embeddings, vector databases, new news sources, preference changes, agents, auth, dashboards, or notifications.
- Keep `ArticleEnricher` as the only article-level OpenAI implementation.
- All schema changes must be backward compatible and reversible through Alembic.

## File Map

- Create `shared/procuresignal/enrichment/policy.py` — immutable policy parsing and per-run budget accounting.
- Create `shared/procuresignal/enrichment/fingerprint.py` — canonical versioned content fingerprints.
- Create `shared/procuresignal/enrichment/deterministic.py` — local extraction, scoring, and extractive summaries.
- Create `shared/procuresignal/enrichment/router.py` — pure route selection and stable reasons.
- Create `shared/procuresignal/enrichment/cache.py` — async validated cache repository.
- Modify `shared/procuresignal/enrichment/pipeline.py` — single cascade orchestrator and metrics.
- Modify `shared/procuresignal/enrichment/enricher.py` — expose validated `EnrichmentOutput` conversion without duplicating OpenAI access.
- Modify `shared/procuresignal/enrichment/__init__.py` — export the new public enrichment interfaces.
- Modify `shared/procuresignal/models/articles.py` — processed audit columns.
- Create `shared/procuresignal/models/enrichment.py` — cache ORM model.
- Modify `shared/procuresignal/models/__init__.py` — export cache model.
- Create `migrations/versions/f6a7b8_add_enrichment_routing_cache.py` — routing metadata and cache schema.
- Modify `worker/tasks.py` — policy-aware task construction and route metrics.
- Create `tests/unit/test_enrichment_policy.py`, `test_enrichment_deterministic.py`, `test_enrichment_router.py`, `test_enrichment_cache.py`, and `test_enrichment_pipeline.py`.
- Modify `tests/unit/test_enrichment.py`, `tests/unit/test_tasks.py`, `tests/unit/test_models.py`, and `tests/integration/test_api.py` for regressions and migration-compatible models.
- Create `tests/fixtures/enrichment_evaluation.json` and `tests/unit/test_enrichment_evaluation.py` — fixed call-avoidance and coverage gate.

---

### Task 1: Policy, Fingerprints, And Hard Budgets

**Files:**
- Create: `shared/procuresignal/enrichment/policy.py`
- Create: `shared/procuresignal/enrichment/fingerprint.py`
- Create: `tests/unit/test_enrichment_policy.py`
- Modify: `shared/procuresignal/enrichment/__init__.py`

**Interfaces:**
- Produces `EnrichmentPolicy.from_env(environ: Mapping[str, str] | None = None) -> EnrichmentPolicy`.
- Produces `EnrichmentBudget.reserve(estimated_tokens: int) -> bool`, `record_usage(actual_tokens: int) -> None`, and read-only counters.
- Produces `content_fingerprint(article: RawArticle, *, policy_version: str, taxonomy_version: str) -> str`.

- [ ] **Step 1: Write failing policy, budget, and fingerprint tests**

Add tests that assert these exact defaults and boundaries:

```python
def test_policy_defaults_are_balanced():
    policy = EnrichmentPolicy.from_env({})
    assert policy.min_relevance == 0.35
    assert policy.min_deterministic_confidence == 0.72
    assert policy.max_llm_calls == 5
    assert policy.max_llm_tokens == 6000
    assert policy.summary_max_chars == 420
    assert policy.policy_version == "cost-v1"
    assert policy.taxonomy_version == "signals-v1"

def test_budget_enforces_call_and_token_caps():
    budget = EnrichmentBudget(max_calls=1, max_tokens=100)
    assert budget.reserve(80) is True
    assert budget.reserve(1) is False
    budget.record_usage(65)
    assert budget.calls_reserved == 1
    assert budget.tokens_used == 65

def test_fingerprint_is_content_and_version_stable(raw_article):
    first = content_fingerprint(raw_article, policy_version="cost-v1", taxonomy_version="signals-v1")
    second = content_fingerprint(raw_article, policy_version="cost-v1", taxonomy_version="signals-v1")
    changed = content_fingerprint(raw_article, policy_version="cost-v2", taxonomy_version="signals-v1")
    assert first == second
    assert first != changed
```

Also test whitespace/case normalization, language sensitivity, invalid floats outside 0–1, non-positive caps, and non-integer environment values.

- [ ] **Step 2: Run tests and verify missing interfaces fail**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment_policy.py -v`

Expected: collection fails because `policy.py` and `fingerprint.py` do not exist.

- [ ] **Step 3: Implement immutable policy and reservation accounting**

Use frozen/slotted dataclasses. Environment names are:

```python
ENRICH_MIN_RELEVANCE
ENRICH_MIN_DETERMINISTIC_CONFIDENCE
ENRICH_MAX_LLM_CALLS
ENRICH_MAX_LLM_TOKENS
ENRICH_SUMMARY_MAX_CHARS
ENRICH_POLICY_VERSION
ENRICH_TAXONOMY_VERSION
```

`reserve()` increments reserved calls and reserved tokens atomically within the in-process run only when both caps remain satisfied. `record_usage()` records actual non-negative tokens without releasing the attempted call.

- [ ] **Step 4: Implement canonical SHA-256 fingerprints**

Normalize each text field with Unicode NFKC, lowercase, collapse whitespace, and preserve field boundaries. Hash a JSON array containing policy version, taxonomy version, language, title, description, and snippet with deterministic separators.

- [ ] **Step 5: Run focused quality gates**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment_policy.py -v
.venv/bin/ruff check shared/procuresignal/enrichment/policy.py shared/procuresignal/enrichment/fingerprint.py tests/unit/test_enrichment_policy.py
.venv/bin/mypy shared/procuresignal/enrichment/policy.py shared/procuresignal/enrichment/fingerprint.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add shared/procuresignal/enrichment/policy.py shared/procuresignal/enrichment/fingerprint.py shared/procuresignal/enrichment/__init__.py tests/unit/test_enrichment_policy.py
git commit -m "Add enrichment policy budgets and fingerprints"
```

### Task 2: Deterministic Analysis And Pure Routing

**Files:**
- Create: `shared/procuresignal/enrichment/deterministic.py`
- Create: `shared/procuresignal/enrichment/router.py`
- Create: `tests/unit/test_enrichment_deterministic.py`
- Create: `tests/unit/test_enrichment_router.py`
- Modify: `shared/procuresignal/enrichment/__init__.py`

**Interfaces:**
- Produces `DeterministicAnalysis(output: EnrichmentOutput, relevance: float, confidence: float)`.
- Produces `DeterministicEnricher.analyze(article: RawArticle, *, summary_max_chars: int) -> DeterministicAnalysis`.
- Produces `EnrichmentRoute` enum values `cached`, `deterministic`, `llm`, `skipped`, `deferred`.
- Produces `RouteDecision(route: EnrichmentRoute, reason: str, confidence: float)`.
- Produces `EnrichmentRouter.decide(*, cache_hit: bool, relevance: float, confidence: float, policy: EnrichmentPolicy, budget_available: bool) -> RouteDecision`.

- [ ] **Step 1: Write failing deterministic extraction tests**

Use articles containing explicit tariff, strike, supplier, and region language. Assert:

```python
analysis = DeterministicEnricher().analyze(article, summary_max_chars=120)
assert analysis.output.category == "automotive"
assert analysis.output.signal_tags == ["tariff"]
assert analysis.output.detected_suppliers == ["Bosch"]
assert analysis.output.detected_regions == ["Germany"]
assert len(analysis.output.summary) <= 120
assert 0.0 <= analysis.relevance <= 1.0
assert 0.0 <= analysis.confidence <= 1.0
```

Cover description → snippet → title summary fallback, stable truncation, no-signal general news, multiple signals, and entity de-duplication.

- [ ] **Step 2: Write the complete routing decision table as parameterized failing tests**

The table is evaluated in priority order:

```python
(
    # cache, relevance, confidence, budget, expected route, reason
    (True, 0.1, 0.1, False, "cached", "compatible_cache_hit"),
    (False, 0.34, 0.99, True, "skipped", "below_relevance_threshold"),
    (False, 0.35, 0.72, True, "deterministic", "deterministic_confident"),
    (False, 0.90, 0.71, True, "llm", "ambiguous_relevant"),
    (False, 0.90, 0.71, False, "deferred", "llm_budget_exhausted"),
)
```

- [ ] **Step 3: Run tests and confirm missing modules fail**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v`

Expected: collection fails for missing modules.

- [ ] **Step 4: Implement deterministic analysis using existing business rules**

Reuse `SignalClassifier`, `extract_suppliers_from_text`, `extract_regions_from_text`, canonical category helpers, and `EnrichmentOutput`. Do not duplicate keyword taxonomies. Confidence combines signal confidence, entity evidence, source/query-group category evidence, and text completeness using documented bounded weights that sum to 1. Relevance uses procurement signals, procurement query groups, entities, and source/category evidence; expose constants for each weight.

- [ ] **Step 5: Implement the pure router and stable reasons**

Use `str, Enum` for `EnrichmentRoute`; do not call databases, OpenAI, or mutate budget inside `decide()`.

- [ ] **Step 6: Run focused tests and quality gates**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py -v
.venv/bin/ruff check shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py
.venv/bin/mypy shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add shared/procuresignal/enrichment/deterministic.py shared/procuresignal/enrichment/router.py shared/procuresignal/enrichment/__init__.py tests/unit/test_enrichment_deterministic.py tests/unit/test_enrichment_router.py
git commit -m "Add deterministic enrichment routing"
```

### Task 3: Auditable Models, Migration, And Persistent Cache

**Files:**
- Modify: `shared/procuresignal/models/articles.py`
- Create: `shared/procuresignal/models/enrichment.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Create: `migrations/versions/f6a7b8_add_enrichment_routing_cache.py`
- Create: `shared/procuresignal/enrichment/cache.py`
- Create: `tests/unit/test_enrichment_cache.py`
- Modify: `tests/unit/test_models.py`

**Interfaces:**
- Produces ORM model `EnrichmentCacheEntry` with unique `(content_fingerprint, policy_version, taxonomy_version)`.
- Produces `CachedEnrichment(output: EnrichmentOutput, original_method: str)`.
- Produces `EnrichmentCache.get(session, *, fingerprint, policy_version, taxonomy_version) -> CachedEnrichment | None`.
- Produces `EnrichmentCache.put(session, *, fingerprint, policy_version, taxonomy_version, output, original_method) -> None`.

- [ ] **Step 1: Write failing model and cache tests**

Assert processed model defaults/audit fields, cache round-trip, hit count increment, corrupt payload treated as a miss, incompatible version miss, and only `deterministic`/`llm` original methods accepted.

Use an in-memory async SQLite database with `Base.metadata.create_all` and assert the second `get()` returns the same validated `EnrichmentOutput` while `hit_count` advances.

- [ ] **Step 2: Run focused tests and confirm schema/interfaces fail**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_models.py tests/unit/test_enrichment_cache.py -v`

Expected: failures for missing model, columns, and repository.

- [ ] **Step 3: Add processed audit columns and cache model**

Processed columns:

```python
enrichment_method: Mapped[str | None]
enrichment_reason: Mapped[str | None]
enrichment_policy_version: Mapped[str | None]
content_fingerprint: Mapped[str | None]
deterministic_confidence: Mapped[float | None]
llm_used: Mapped[bool]
```

Use nullable fields for historical rows and `llm_used` with Python/server default false. Cache payload is JSON, hit count defaults to zero, and timestamps use the shared base conventions.

- [ ] **Step 4: Add the reversible Alembic migration**

Set `down_revision = "e5f6a7_add_risk_event_scan_tracking"`. Add the six processed columns, create `enrichment_cache`, add its unique constraint and fingerprint lookup index. Downgrade drops the cache table/index before processed columns.

- [ ] **Step 5: Implement validated async cache operations**

Serialize with `EnrichmentOutput.model_dump(mode="json")`; validate reads with `EnrichmentOutput.model_validate`. On validation failure, log the fingerprint and return `None` without incrementing hit count. `put()` uses select-then-insert/update in the supplied session and never commits independently; the pipeline owns transaction boundaries.

- [ ] **Step 6: Run cache, model, migration, and quality gates**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/unit/test_models.py tests/unit/test_enrichment_cache.py -v
DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase2-migration.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase2-migration.db .venv/bin/alembic downgrade e5f6a7_add_risk_event_scan_tracking
.venv/bin/alembic heads
.venv/bin/ruff check shared/procuresignal/models shared/procuresignal/enrichment/cache.py migrations/versions/f6a7b8_add_enrichment_routing_cache.py tests/unit/test_enrichment_cache.py
.venv/bin/mypy shared/procuresignal/models shared/procuresignal/enrichment/cache.py
```

Expected: tests pass, migration upgrades/downgrades, exactly one Alembic head, lint/types pass.

- [ ] **Step 7: Commit**

```bash
git add shared/procuresignal/models shared/procuresignal/enrichment/cache.py migrations/versions/f6a7b8_add_enrichment_routing_cache.py tests/unit/test_models.py tests/unit/test_enrichment_cache.py
git commit -m "Add versioned enrichment cache schema"
```

### Task 4: Integrate The Cascade Into Enrichment Pipeline

**Files:**
- Modify: `shared/procuresignal/enrichment/enricher.py`
- Modify: `shared/procuresignal/enrichment/pipeline.py`
- Modify: `shared/procuresignal/enrichment/__init__.py`
- Create: `tests/unit/test_enrichment_pipeline.py`
- Modify: `tests/unit/test_enrichment.py`

**Interfaces:**
- Produces `EnrichmentMetrics` with exactly `cached`, `deterministic`, `llm`, `skipped`, `deferred`, `failed`, `cache_misses`, `llm_calls`, `llm_tokens`, and `avoided_llm_calls` counters.
- `EnrichmentPipeline.__init__` accepts `llm_client`, `policy`, `router`, `deterministic_enricher`, and `cache` dependencies.
- `process_raw_articles(...) -> EnrichmentRunResult`, where result contains saved count plus all route metrics.

- [ ] **Step 1: Write failing zero-call, LLM, fallback, and idempotency tests**

Use a spy client whose `call()` count is asserted. Required cases:

- Cache hit persists completed metadata and makes zero calls.
- Deterministic confidence route makes zero calls.
- Relevant ambiguous article calls OpenAI once when reservation succeeds.
- Budget exhaustion returns deferred and persists no completed row.
- OpenAI exception uses deterministic fallback only when fallback confidence meets policy.
- Corrupt cache becomes a miss and continues routing.
- Reprocessing a raw ID creates no second processed row.
- Every candidate increments exactly one route counter.

- [ ] **Step 2: Run tests and verify the old pipeline fails the new contract**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py -v`

Expected: failures for missing result/metrics/dependencies and unconditional LLM behavior.

- [ ] **Step 3: Separate OpenAI output generation from model persistence**

Add `ArticleEnricher.generate_output(article) -> EnrichmentOutput | None`. Keep `enrich()` as a compatibility wrapper that calls `generate_output()` and converts output to `NewsArticleProcessed`. Do not add a second OpenAI caller.

- [ ] **Step 4: Implement cascade orchestration and one transaction owner**

For each unprocessed article: fingerprint → cache → deterministic analysis → route → optional budget reservation/OpenAI → validated fallback → processed record/cache write. Populate all audit fields. Commit once per batch, roll back on database failure, and keep deferred raw articles eligible because no completed processed row is inserted.

- [ ] **Step 5: Make metrics and skipped-count semantics explicit**

`skipped` counts only below-relevance decisions. Already-processed input IDs are reported separately as `already_processed`. `avoided_llm_calls = cached + deterministic + skipped`; deferred is not counted as avoided success.

- [ ] **Step 6: Run focused tests and quality gates**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py -v
.venv/bin/ruff check shared/procuresignal/enrichment tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py
.venv/bin/mypy shared/procuresignal/enrichment
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add shared/procuresignal/enrichment tests/unit/test_enrichment.py tests/unit/test_enrichment_pipeline.py
git commit -m "Route enrichment through cost controls"
```

### Task 5: Worker Metrics And Fixed Evaluation Gate

**Files:**
- Modify: `worker/tasks.py`
- Modify: `tests/unit/test_tasks.py`
- Create: `tests/fixtures/enrichment_evaluation.json`
- Create: `tests/unit/test_enrichment_evaluation.py`

**Interfaces:**
- Worker task result exposes the pipeline metrics without changing task name, queue, retries, or schedule.
- Evaluation fixture schema contains article input, expected relevance class, and baseline supplier/region/category/signal sets.

- [ ] **Step 1: Write failing worker task result tests**

Patch `EnrichmentPolicy.from_env`, pipeline construction, and session scope. Assert task results retain `status`, `enriched_count`, `skipped_count`, `error_count`, and timestamp while adding `routes`, `llm_calls`, `llm_tokens`, and `avoided_llm_calls`. Assert missing OpenAI key does not prevent deterministic/cache processing; the client is optional until the router chooses LLM.

- [ ] **Step 2: Create the fixed representative evaluation fixture**

Add at least 20 deterministic JSON records covering relevant clear signals, relevant ambiguity, irrelevant general news, exact/near duplicate content, English/German/French text, supplier-rich text, region-rich text, and missing descriptions. Store baseline extraction sets explicitly for each accepted record.

- [ ] **Step 3: Write the failing evaluation test**

Run all fixture records through policy + deterministic analysis + router with a five-call budget. Assert:

```python
assert 0.70 <= avoided_calls / accepted_candidates <= 0.85
assert supplier_coverage >= baseline_supplier_coverage - 0.05
assert region_coverage >= baseline_region_coverage - 0.05
assert category_coverage >= baseline_category_coverage - 0.05
assert signal_coverage >= baseline_signal_coverage - 0.05
```

Use exact set-recall calculations in a named helper; no network or OpenAI call is allowed.

- [ ] **Step 4: Run tests and verify worker/evaluation gaps fail**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_tasks.py tests/unit/test_enrichment_evaluation.py -v`

Expected: worker metrics/missing-key behavior and evaluation threshold fail before integration/tuning.

- [ ] **Step 5: Integrate lazy OpenAI construction and route metrics**

Construct policy at run start. Pass an optional lazy client factory into the pipeline so deterministic/cache-only runs do not require `OPENAI_API_KEY`. Preserve current Celery metadata and error/retry behavior.

- [ ] **Step 6: Tune only documented deterministic weights/threshold defaults**

Use fixture results to meet the 70–85% band and five-point extraction limits. Do not encode fixture headlines or suppliers into production rules; improvements must use reusable taxonomy/entity/category evidence.

- [ ] **Step 7: Run worker/evaluation and full backend tests**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/unit/test_tasks.py tests/unit/test_enrichment_evaluation.py -v
PYTHONPATH=shared .venv/bin/pytest tests -q
.venv/bin/ruff check .
.venv/bin/mypy api worker shared
```

Expected: evaluation within target band, extraction gates pass, full backend passes, lint/types clean.

- [ ] **Step 8: Commit**

```bash
git add worker/tasks.py tests/unit/test_tasks.py tests/fixtures/enrichment_evaluation.json tests/unit/test_enrichment_evaluation.py
git commit -m "Expose enrichment savings and evaluation gate"
```

### Task 6: Integration, Migration, And Full-Stack Verification

**Files:**
- Modify as required by compatibility failures: `tests/integration/test_api.py`
- Create: `docs/superpowers/reports/2026-07-13-cost-optimized-enrichment.md`

**Interfaces:**
- Consumes all Phase 2 interfaces and produces the verified completion record.

- [ ] **Step 1: Add an integration test for persisted audit metadata**

Seed one clear deterministic article and one cache-compatible article in isolated SQLite. Run the pipeline twice and assert completed rows expose method, reason, policy version, fingerprint, confidence, and `llm_used=False`, with no duplicate processed row and cache hit count incremented.

- [ ] **Step 2: Run migration and integration tests**

Run:

```bash
PYTHONPATH=shared .venv/bin/pytest tests/integration/test_api.py tests/unit/test_enrichment_pipeline.py tests/unit/test_enrichment_cache.py -v
DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase2-final.db .venv/bin/alembic upgrade head
.venv/bin/alembic heads
```

Expected: tests pass and exactly one Alembic head is reported.

- [ ] **Step 3: Run complete backend verification**

Run:

```bash
.venv/bin/black --check .
.venv/bin/ruff check .
.venv/bin/mypy api worker shared
PYTHONPATH=shared .venv/bin/pytest tests -q
```

Expected: all exit zero.

- [ ] **Step 4: Run complete frontend and configuration verification**

Run from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test:run
npm run build
```

Then run from repository root:

```bash
docker compose config --quiet
git diff --check
```

Expected: all exit zero. Record Node/Vite warnings separately from failures.

- [ ] **Step 5: Write the completion report with measured evidence**

Document route counts, avoidance ratio, extraction coverage by dimension, token/call caps, cache behavior, migrations, all verification counts, remaining limitations, and the exact distinction between Compose configuration validation and image builds. Do not update `docs/interview-preparation.md`; it remains deferred until Phase 10.

- [ ] **Step 6: Check and commit the report**

Run:

```bash
rg -n 'T[B]D|T[O]DO|F[I]XME|fill.in|result.goes.here' docs/superpowers/reports/2026-07-13-cost-optimized-enrichment.md
git diff --check
git status --short
```

Expected: the incomplete-marker scan prints nothing and status contains only intended Phase 2 documentation plus the preserved untracked interview document.

```bash
git add tests/integration/test_api.py docs/superpowers/reports/2026-07-13-cost-optimized-enrichment.md
git commit -m "Document cost-optimized enrichment results"
```
