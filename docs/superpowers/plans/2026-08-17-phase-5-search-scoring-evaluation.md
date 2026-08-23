# Phase 5: Search, Scoring and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace substring matching with retrieval a procurement team can trust — lexical plus
semantic, ranked, measured against a labelled set, and instrumented so a regression is visible
before a customer finds it.

**Architecture:** Postgres full-text search and pgvector embeddings, fused by reciprocal rank
fusion, behind one search service. Relevance feedback is captured from day one so learning-to-rank
has data when it is worth building. Supplier impact scoring is deterministic and explainable, not
a model. An offline evaluation harness runs in CI with a regression floor.

**Tech Stack:** PostgreSQL 15 + pgvector, SQLAlchemy async, Alembic, OpenAI embeddings
(`text-embedding-3-small`), Celery, FastAPI, Next.js 16.

## Global Constraints

- **Every dialect-specific query is tested against real PostgreSQL.** CI already runs a Postgres
  service that no test connects to; that gap is what let six over-length Alembic revision IDs pass
  on SQLite in Phase 3. Task 1 closes it before anything depends on it.
- A skipped test is not a passing test. The Postgres suite runs in CI with `REQUIRE_POSTGRES=1`,
  under which a skip is a failure.
- **Embeddings are never faked into the production column.** A hash-based placeholder sharing a
  column with real vectors silently corrupts every ranking that reads it. No key means semantic
  search is off and retrieval degrades to lexical, reported honestly in the response.
- The embedding model name is stored on every row. Changing models mixes two vector spaces, whose
  distances are not comparable, and that failure is invisible without the column.
- Search is read-only over a global article corpus; feedback and impact scores are
  organization-scoped and audited like every other tenant-owned write.
- Impact scores ship with their inputs. A procurement decision defended with an unexplainable
  number is not defensible.
- No new external service. D4 locks vector search to pgvector in the existing instance.
- Backend gate per task: `pytest tests/ -q --no-cov`, `pytest -m postgres` against a real
  instance, `black --check .`, `ruff check .`, `mypy api worker shared`. Frontend tasks add tests,
  typecheck, lint, build, `verify:routes`.

## Why the test harness comes first

Phases 0–4 produced eight defects that passing tests did not catch, and every one lived just
outside the boundary being verified — the source tree but not the container, Turbopack but not
webpack, ASCII but not Unicode, SQLite but not Postgres. This phase's core artifacts
(`tsvector`, `GIN`, `vector`, `<=>`) do not exist in SQLite at all. Writing them first and
verifying later would repeat the pattern deliberately.

## File Structure

- `shared/procuresignal/search/lexical.py`: tsquery construction and ranked lexical retrieval.
- `shared/procuresignal/search/embeddings.py`: provider port, OpenAI provider, backfill.
- `shared/procuresignal/search/hybrid.py`: fusion, degradation, the one entry point the API calls.
- `shared/procuresignal/models/search.py`: `ArticleEmbedding`, `SearchFeedback`.
- `shared/procuresignal/scoring/impact.py`: supplier exposure scoring with breakdown.
- `shared/procuresignal/evaluation/metrics.py`: precision@k, recall@k, MRR, nDCG.
- `shared/procuresignal/evaluation/harness.py`: runs a golden set, returns a report.
- `api/routers/articles.py` (search rewritten), `api/routers/search_feedback.py`,
  `api/routers/impact.py`.
- `scripts/evaluate_search.py`: CLI gate.
- `frontend/components/search-view.tsx`, `frontend/components/impact-badge.tsx`.

---

### Task 1: Real PostgreSQL in the test suite, and pgvector

**Files:**
- Modify: `tests/conftest.py`, `pyproject.toml`, `.github/workflows/ci.yml`, `docker-compose.yml`
- Create: `migrations/versions/q2r3s4_pgvector.py` (down_revision `p0q1r2_notifications`)
- Test: `tests/postgres/test_pg_harness.py`, `tests/unit/test_ci_workflow.py` (extend)

**Interfaces:**
- Produces: `pg_session` fixture (async session against `TEST_DATABASE_URL`), `postgres` pytest
  marker, `pgvector` dependency, `vector` extension available in dev, CI and test databases.

**Design notes:**

`pg_session` creates the schema by running Alembic upgrade head against a throwaway database, not
by `metadata.create_all`. Creating tables from the ORM is exactly the check that cannot catch a
migration that disagrees with the models, and Phase 3 shipped that bug.

The marker skips when `TEST_DATABASE_URL` is unset so local `pytest` stays fast, and
`REQUIRE_POSTGRES=1` converts that skip into a failure so CI can never go quietly green. The CI
image becomes `pgvector/pgvector:pg15`; `postgres:15-alpine` has no extension to enable.

`CREATE EXTENSION IF NOT EXISTS vector` is dialect-guarded: the same migration must remain a
no-op under SQLite or every existing test breaks.

- [x] Step 1: Failing test — `pg_session` round-trips a row and reports `vector` present
- [x] Step 2: Fixture, marker, dependency, migration, CI and compose image swap
- [x] Step 3: Extend `test_ci_workflow.py` — pgvector image, `REQUIRE_POSTGRES=1` present
- [x] Step 4: Prove the guard by unsetting the URL under `REQUIRE_POSTGRES=1` and seeing red
- [x] Step 5: Full gate, commit, push

---

### Task 2: Lexical search on PostgreSQL full-text

**Files:**
- Create: `shared/procuresignal/search/lexical.py`
- Create: `migrations/versions/r3s4t5_article_fts.py`
- Test: `tests/unit/test_lexical_search.py`, `tests/postgres/test_lexical_search_pg.py`

**Interfaces:**
- Produces: `async def lexical_search(session, *, query: str, limit: int, days: int) -> list[Hit]`
  where `Hit` is `(processed_id: int, score: float)`; `def build_tsquery(query: str) -> str`.

**Design notes:**

A generated `tsvector` column over title, summary and snippet with a GIN index, weighted so a term
in the title outranks the same term in a snippet (`setweight` A/B/C). `websearch_to_tsquery`
parses user input, which means quoted phrases and `-exclusions` work and a stray `&` cannot
produce a syntax error the user sees as a 500.

Ranking is `ts_rank_cd`, which accounts for term proximity — "port strike" should not rank a
document mentioning ports and strikes ten paragraphs apart above one about a port strike.

Stemming is the point: today `ILIKE '%disruption%'` misses "disruptions" in a German-language
title entirely. Language configuration is per article language where known, `simple` otherwise —
`english` stemming applied to German text produces wrong stems, which is worse than none.

The SQLite path keeps the existing ILIKE behaviour so development and the non-Postgres suite work,
and a test pins that both paths return the same *ordering* on a shared fixture where they agree.

- [x] Step 1: Failing unit tests — tsquery escaping, phrase, exclusion, empty and punctuation-only
- [x] Step 2: Failing Postgres tests — stemming, title weighting, proximity, index is used
      (`EXPLAIN` shows a bitmap index scan, not a sequential scan)
- [x] Step 3: Migration and implementation
- [x] Step 4: Full gate, commit, push

---

### Task 3: Article embeddings

**Files:**
- Create: `shared/procuresignal/search/embeddings.py`,
  `shared/procuresignal/models/search.py`
- Create: `migrations/versions/s4t5u6_article_embeddings.py`
- Modify: `worker/tasks.py`, `worker/celery_config.py`
- Test: `tests/unit/test_embeddings.py`, `tests/postgres/test_embeddings_pg.py`

**Interfaces:**
- Produces: `EmbeddingProvider` protocol (`name: str`, `dimensions: int`,
  `async def embed(texts: list[str]) -> list[list[float]]`); `OpenAIEmbeddingProvider`;
  `async def embed_pending_articles(session, *, provider, limit=200) -> int`;
  `ArticleEmbedding(processed_article_id, model, dimensions, embedding, created_at)`.

**Design notes:**

`text-embedding-3-small` at 1536 dimensions: an order of magnitude cheaper than `-3-large` for a
30-day corpus of news snippets, where the ranking difference does not justify the cost. Batched
requests, `tenacity` retry on 429, and the Phase 3 budget guard applies — embedding every article
for every tenant is exactly the runaway the budget cap exists to stop.

Unique on `(processed_article_id, model)`, so re-running is idempotent and a model migration adds
rows rather than overwriting the vectors currently serving queries.

Selection skips articles that already have a row for the active model, ordered by recency, not by
id ascending — the Phase 3 sanctions screener starved on exactly that pattern, re-processing the
same earliest thousand rows forever.

Tests use a deterministic fake provider. The real client is exercised by one test that asserts the
request shape against a stubbed transport, never the live API.

- [x] Step 1: Failing tests — idempotency, batching, dimension mismatch rejected, budget refusal
- [x] Step 2: Failing Postgres test — vector round-trip and cosine ordering via `<=>`
- [x] Step 3: Model, migration, provider, backfill, Celery task with freshness metric
- [x] Step 4: Full gate, commit, push

---

### Task 4: Hybrid retrieval and the search API

**Files:**
- Create: `shared/procuresignal/search/hybrid.py`
- Modify: `api/routers/articles.py`, `api/schemas/article.py`,
  `shared/procuresignal/observability/metrics.py`
- Test: `tests/unit/test_hybrid_search.py`, `tests/integration/test_search_api.py`

**Interfaces:**
- Produces: `async def search(session, *, query, limit, days, provider=None) -> SearchOutcome`
  with `SearchOutcome(hits: list[ScoredHit], mode: str, lexical_count: int, vector_count: int)`
  and `mode` one of `hybrid`, `lexical`, `degraded`.

**Design notes:**

Reciprocal rank fusion with k=60, not score averaging: cosine distance and `ts_rank_cd` are not on
a comparable scale, and normalising them per query makes the weighting depend on the result set
rather than on relevance. RRF needs only the ranks.

Degradation is explicit and reported. No embedding provider, no embeddings yet, or a provider
error means lexical results with `mode="lexical"` — never an empty page and never a 500. The mode
travels in the response because a support question about bad results starts with which retriever
produced them.

`_score_search_result` in `api/routers/articles.py:90` is deleted here, not left beside its
replacement.

Metrics: `SEARCH_QUERIES{mode}` counter and a latency histogram, so D4's stated revisit trigger
(p99 above 200ms) is measurable rather than aspirational.

- [x] Step 1: Failing tests — fusion order, tie handling, each degradation path, mode reported
- [x] Step 2: Implement, rewrite the endpoint, delete the old scorer
- [x] Step 3: Verify against a real corpus in Postgres, reading the top ten for two real queries
- [x] Step 4: Full gate, commit, push

---

### Task 5: Relevance feedback capture

**Files:**
- Create: `api/routers/search_feedback.py`, `api/schemas/search_feedback.py`
- Modify: `shared/procuresignal/models/search.py`
- Create: `migrations/versions/t5u6v7_search_feedback.py`
- Test: `tests/integration/test_search_feedback_api.py`

**Interfaces:**
- Produces: `POST /api/search/feedback`, `GET /api/search/feedback` (admin, for export);
  `SearchFeedback(organization_id, user_id, query_text, query_fingerprint, processed_article_id,
  rank_position, signal, mode, created_at)` with `signal` in `click|useful|not_useful`.

**Design notes:**

What makes this trainable later is `rank_position` and `mode`: a click on result 1 and a click on
result 9 carry opposite information about the ranker, and without the position the whole table is
unusable for LTR. `query_fingerprint` is a normalised hash so the same query typed with different
spacing groups.

Unique on `(user_id, query_fingerprint, processed_article_id, signal)` — a double-click is one
signal, and a user who clicks, returns and clicks again has not given two independent labels.

Storing the raw query text is a GDPR-relevant decision, not an incidental one: it is user-entered
content tied to an identified person, so it is in scope for Phase 7's erasure path and is recorded
as such in that phase's inventory now rather than discovered later.

- [x] Step 1: Failing tests — capture, dedupe, cross-tenant isolation, unknown article rejected
- [x] Step 2: Model, migration, endpoints, audit on write
- [x] Step 3: Full gate, commit, push

---

### Task 6: Supplier impact scoring

**Files:**
- Create: `shared/procuresignal/scoring/impact.py`, `api/routers/impact.py`,
  `api/schemas/impact.py`
- Test: `tests/unit/test_impact_scoring.py`, `tests/integration/test_impact_api.py`

**Interfaces:**
- Produces: `def score_supplier(events: list[RiskEvent], *, now: datetime) -> ImpactScore` with
  `ImpactScore(value: float, band: str, drivers: list[Driver])`;
  `async def watched_impact(session, *, organization_id) -> list[SupplierImpact]`;
  `GET /api/impact` and `GET /api/impact/{supplier_public_id}`.

**Design notes:**

Deterministic and explainable: severity weight × exponential recency decay (14-day half-life,
matching the 30-day retention window) × event confidence, summed with diminishing returns so
thirty medium articles about one incident cannot outrank one critical sanctions listing. Sanctions
carry a floor: any active sanctions match puts a supplier in the top band regardless of the rest,
because that is a compliance stop, not a risk gradient.

`drivers` returns the events that produced the number, ranked by contribution. A score with no
drivers is a number a buyer cannot act on or defend to their own audit function.

Tests assert properties rather than magic constants — more severe never scores lower, older never
scores higher, adding an event never decreases the total — so the weights stay tunable without
rewriting the suite. One test pins the sanctions floor specifically.

- [ ] Step 1: Failing property tests plus the sanctions floor and the empty case
- [ ] Step 2: Implement scoring, then the API over watched suppliers
- [ ] Step 3: Score the seeded corpus and read the output for plausibility
- [ ] Step 4: Full gate, commit, push

---

### Task 7: Evaluation framework

**Files:**
- Create: `shared/procuresignal/evaluation/metrics.py`,
  `shared/procuresignal/evaluation/harness.py`, `scripts/evaluate_search.py`
- Create: `tests/fixtures/golden_queries.json`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/unit/test_evaluation_metrics.py`, `tests/postgres/test_search_evaluation.py`

**Interfaces:**
- Produces: `precision_at_k`, `recall_at_k`, `mean_reciprocal_rank`, `ndcg_at_k`;
  `async def run_evaluation(session, *, cases, search_fn) -> EvaluationReport` with
  `EvaluationReport(mean_precision_at_5, mean_recall_at_10, mrr, ndcg_at_10, per_case)`.

**Design notes:**

Twelve hand-labelled procurement queries against a fixed fixture corpus — supplier names, risk
phrasings, a multilingual case, a spelling variant, and two queries whose correct answer is *no
results*, since a system that always returns something is not measurably better than one that
returns nothing.

Metric implementations are tested against worked examples computed by hand, not against
themselves. An nDCG implementation that agrees with its own bug is the classic way an evaluation
harness certifies a regression.

CI runs the harness with a floor committed alongside the labels. Below the floor the build fails,
which makes this a gate rather than a dashboard. The floor moves up when retrieval improves and
never down without an accompanying note in the plan.

- [ ] Step 1: Failing metric tests with hand-computed expectations
- [ ] Step 2: Implement metrics, then the harness and the golden set
- [ ] Step 3: Establish the floor from a real run; add the CI step
- [ ] Step 4: Prove the gate by degrading the ranker and watching it fail
- [ ] Step 5: Full gate, commit, push

---

### Task 8: Search and impact UI

**Files:**
- Create: `frontend/components/search-view.tsx`, `frontend/app/search/page.tsx`,
  `frontend/components/impact-badge.tsx`
- Modify: `frontend/lib/api.ts`, `frontend/lib/types.ts`, `frontend/components/header.tsx`,
  `frontend/components/watchlist-view.tsx`
- Test: `frontend/__tests__/search-view.test.tsx`, `frontend/__tests__/impact-badge.test.tsx`

**Design notes:**

Feedback is captured from the interaction the user already performs — opening a result — plus an
explicit "not relevant" control. A thumbs-up nobody clicks produces a table nobody can train on.

When `mode` is `lexical` the UI says keyword-only rather than pretending semantic ranking ran.
Impact bands appear on watchlist rows, with the drivers on hover, so the score is never a bare
number.

Tests synchronise on loaded content, never on markup present during loading.

- [ ] Step 1: Failing tests, implement, full frontend gate including `verify:routes`, commit, push

---

## Self-Review

**Spec coverage:** The roadmap's Phase 5 line is "pgvector semantic search, feedback capture,
impact scoring, evaluation framework" — Tasks 3–4, 5, 6, 7 respectively. Task 1 is the
prerequisite that makes 2–4 verifiable, Task 2 is the lexical half of hybrid retrieval that
"semantic search" alone would leave as the existing ILIKE, and Task 8 is the surface. The D7 note
that LTR's prerequisite is feedback capture is satisfied by Task 5's `rank_position` and `mode`.

**Ordering:** 2 and 3 need 1's Postgres fixture and extension. 4 needs 2 and 3. 5 records the
`mode` that 4 produces. 7 evaluates 4. 8 consumes 4, 5 and 6. Task 6 depends only on Phase 2
supplier identity and Phase 3 risk events, both shipped, so it can move earlier if 3 blocks on
API cost.

**Type consistency:** `Hit` (Task 2) is the input to `search()` (Task 4), which returns
`SearchOutcome.mode`, the same string Task 5 stores and Task 8 renders. `ImpactScore.drivers`
(Task 6) is what Task 8's badge shows on hover.

**Deliberately out of scope:**

- **Learning-to-rank.** D7 defers it until the feedback table supports a train/test split. Task 5
  builds the prerequisite; training on twelve labels would be theatre.
- **OpenSearch.** D7's trigger is Postgres p99 above 500ms; Task 4 adds the histogram that would
  demonstrate it.
- **Query understanding** (entity linking in queries, spelling correction). Real improvements, but
  they are measurable only once Task 7's harness exists, so they belong after it rather than
  bundled with it.
- **Cross-encoder reranking.** Latency and cost for a gain the evaluation harness cannot yet
  demonstrate.
