# Authoritative Procurement Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe, auditable, registry-driven retrieval layer with authoritative European procurement coverage, structured EU sanctions ingestion, durable source/run state, and deterministic offline verification.

**Architecture:** A versioned typed registry supplies definitions to one generic RSS/Atom adapter and one structured sanctions adapter. Additive raw provenance plus retrieval-run/source-outcome tables preserve lineage, while durable run claims and source circuits make concurrent scheduled retrieval idempotent and failure-isolated. Recorded fixtures—not live internet—form the required test boundary.

**Tech Stack:** Python 3.11, Pydantic 2, httpx, feedparser, SQLAlchemy async, PostgreSQL/SQLite, Alembic, Celery, Pytest, respx, Ruff, Black, MyPy.

## Global Constraints

- Retrieval must make zero OpenAI/LLM calls.
- Existing REST, WebSocket, frontend, NewsAPI, optional GDELT, and worker result contracts remain backward compatible.
- Fetch only registry-declared HTTPS endpoints on approved public hostnames; validate every redirect and reject URL credentials, loopback, link-local, private, reserved, multicast, and unspecified addresses.
- Maximum decoded response size is 5 MiB; maximum redirects is 3; connect timeout is 5 seconds; read timeout is 20 seconds.
- Global source concurrency is 6 and per-host concurrency is 2.
- Transient fetches retry at most 3 attempts; respect `Retry-After` up to 15 minutes; otherwise use bounded exponential backoff with jitter.
- Open a source circuit after 5 consecutive failures for 30 minutes; one half-open success closes it.
- Retrieval-run lease is 65 minutes, exceeding the Celery task's 60-minute hard limit; expired leases are reclaimable.
- Only stable registry IDs may become metric labels; never use article URLs, titles, arbitrary exception strings, credentials, response bodies, or full query strings.
- CI uses recorded RSS/XML/JSON fixtures and must not require internet or provider credentials.
- `docs/interview-preparation.md` remains untouched until Phase 10.

## File Structure

- `shared/procuresignal/retrieval/registry.py`: typed source definitions, validation, versioning, selection, and coverage validation.
- `shared/procuresignal/retrieval/catalog.py`: the reviewed production source catalog; no network logic.
- `shared/procuresignal/retrieval/security.py`: URL/redirect/DNS safety policy and bounded response reading.
- `shared/procuresignal/retrieval/fetching.py`: retry classification and safe HTTP fetch result.
- `shared/procuresignal/retrieval/providers/rss.py`: one-definition RSS/Atom parsing.
- `shared/procuresignal/retrieval/providers/sanctions.py`: official structured EU sanctions parsing.
- `shared/procuresignal/retrieval/deduplication.py`: canonical URL/content fingerprints and within-run deduplication.
- `shared/procuresignal/retrieval/audit.py`: run/source claim and circuit repositories.
- `shared/procuresignal/retrieval/orchestrator.py`: bounded concurrent provider orchestration and aggregate result.
- `shared/procuresignal/retrieval/persistence.py`: additive provenance persistence and final database idempotency.
- `shared/procuresignal/models/retrieval.py`: retrieval run and per-source outcome ORM models.
- `tests/fixtures/retrieval/`: immutable provider payloads and expected contract data.

---

### Task 1: Typed Registry And Coverage Contract

**Files:**
- Create: `shared/procuresignal/retrieval/registry.py`
- Create: `shared/procuresignal/retrieval/catalog.py`
- Create: `tests/fixtures/retrieval/catalog_expected.json`
- Create: `tests/unit/test_source_registry.py`
- Modify: `shared/procuresignal/retrieval/__init__.py`

**Interfaces:**
- Produces: `SourceClass`, `AdapterType`, `ProcurementDomain`, `SourceDefinition`, `SourceRegistry`, `SOURCE_REGISTRY`, and `REGISTRY_VERSION`.
- `SourceRegistry.enabled(*, source_ids: set[str] | None = None) -> tuple[SourceDefinition, ...]` returns deterministic `source_id` order.
- `SourceRegistry.validate_coverage() -> CoverageReport` reports exact missing domains and authority requirements.

- [ ] **Step 1: Write failing registry contract tests**

```python
def test_registry_rejects_unsafe_and_ambiguous_definitions() -> None:
    with pytest.raises(ValueError, match="https"):
        SourceRegistry((definition(endpoint_url="http://example.com/feed"),))
    with pytest.raises(ValueError, match="duplicate source_id"):
        SourceRegistry((definition(source_id="ec"), definition(source_id="ec")))
    with pytest.raises(ValueError, match="domains"):
        SourceRegistry((definition(domains=frozenset()),))


def test_production_registry_meets_phase_3_coverage() -> None:
    report = SOURCE_REGISTRY.validate_coverage()
    assert report.missing_domains == ()
    assert report.missing_authoritative_domains == ()
    assert {"sanctions", "regulation"} <= {
        domain.value for domain in report.authoritative_domains
    }
```

- [ ] **Step 2: Run the registry tests and observe the missing-module failure**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_source_registry.py -v`

Expected: collection fails because `procuresignal.retrieval.registry` does not exist.

- [ ] **Step 3: Implement the exact registry types and invariants**

```python
class SourceClass(StrEnum):
    OFFICIAL = "official"
    ESTABLISHED_MEDIA = "established_media"
    INDUSTRY = "industry"


class AdapterType(StrEnum):
    RSS = "rss"
    STRUCTURED_SANCTIONS = "structured_sanctions"
    NEWSAPI = "newsapi"
    GDELT = "gdelt"


class ProcurementDomain(StrEnum):
    SANCTIONS = "sanctions"
    REGULATION = "regulation"
    LOGISTICS = "logistics"
    COMMODITIES = "commodities"
    FX = "fx"
    SUPPLIER_RISK = "supplier_risk"
    EUROPE_BUSINESS = "europe_business"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    display_name: str
    homepage_url: str
    endpoint_url: str
    adapter: AdapterType
    source_class: SourceClass
    domains: frozenset[ProcurementDomain]
    countries: tuple[str, ...]
    languages: tuple[str, ...]
    poll_minutes: int
    item_limit: int
    expected_content_types: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    trust_seed: float
    license_note: str
    enabled_by_default: bool = True
    parser_hint: str | None = None
```

Validate stable lowercase IDs, ISO-like language/country tokens, `0 <= trust_seed <= 1`,
`5 <= poll_minutes <= 1440`, `1 <= item_limit <= 100`, nonempty license notes, endpoint host
membership in `allowed_hosts`, and HTTPS for homepage/endpoint.

- [ ] **Step 4: Build the initial catalog and immutable expected snapshot**

Create definitions for these reviewed source identities: `eu_commission_press`,
`eu_council_press`, `ecb_press`, `eu_financial_sanctions`, plus verified public machine-readable
European logistics, commodities, and established-business feeds sufficient for the spec's
matrix. For each candidate, record ownership, endpoint, content type, language, usage note,
and a fixture filename in `catalog_expected.json`. A candidate with no stable public endpoint
or incompatible usage terms must be disabled and recorded later in the completion report; it
must not be represented by a guessed URL.

- [ ] **Step 5: Run focused tests and static checks**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_source_registry.py -v`

Expected: all registry tests pass and the snapshot exactly matches enabled IDs/version.

Run: `.venv/bin/ruff check shared/procuresignal/retrieval tests/unit/test_source_registry.py && .venv/bin/mypy shared/procuresignal/retrieval`

Expected: both commands succeed.

- [ ] **Step 6: Commit Task 1**

```bash
git add shared/procuresignal/retrieval tests/fixtures/retrieval/catalog_expected.json tests/unit/test_source_registry.py
git commit -m "Add authoritative procurement source registry"
```

---

### Task 2: Provenance And Retrieval Audit Schema

**Files:**
- Create: `shared/procuresignal/models/retrieval.py`
- Create: `migrations/versions/f8c9d0_add_retrieval_source_audit.py`
- Create: `tests/integration/test_retrieval_audit_migration.py`
- Modify: `shared/procuresignal/models/articles.py`
- Modify: `shared/procuresignal/models/__init__.py`
- Modify: `shared/procuresignal/retrieval/base.py`
- Modify: `tests/unit/test_models.py`

**Interfaces:**
- Extends `RawArticle` with defaulted `source_id`, `source_class`, `source_domains`,
  `source_countries`, `registry_version`, `retrieved_at`, and `source_published_at_raw` fields.
- Produces `NewsRetrievalRun` and `NewsRetrievalSourceOutcome` ORM models.
- `NewsRetrievalRun` owns a unique `run_key`, lease owner/expiry, status, registry version,
  aggregate counts, and timestamps.
- `NewsRetrievalSourceOutcome` is unique on `(run_id, source_id)` and stores stable classified
  counts/state only.

- [ ] **Step 1: Write failing model and populated-migration tests**

```python
def test_raw_article_provenance_defaults_preserve_existing_callers() -> None:
    article = RawArticle(
        provider="rss",
        provider_article_id="ecb-1",
        query_group="fx",
        title="ECB publishes monetary policy update",
        description="Official communication",
        content_snippet="Official communication",
        article_url="https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html",
        canonical_url="https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html",
        source_name="European Central Bank",
        source_url="https://www.ecb.europa.eu/",
        published_at=datetime(2026, 7, 13, 10, 0),
        language="en",
    )
    assert article.source_id is None
    assert article.source_domains == ()
    assert article.retrieved_at is None


async def test_retrieval_outcome_is_unique_per_run_and_source(async_session) -> None:
    run = NewsRetrievalRun(
        run_key="scheduled:2026-07-13T12:00Z",
        status="running",
        registry_version="sources-v1",
        lease_owner="worker-a",
        lease_expires_at=datetime(2026, 7, 13, 13, 5),
        started_at=datetime(2026, 7, 13, 12, 0),
    )
    async_session.add_all([
        NewsRetrievalSourceOutcome(
            run=run,
            source_id="ecb_press",
            status="success",
            attempted_count=1,
            fetched_count=1,
            accepted_count=1,
            inserted_count=1,
            duplicate_count=0,
            rejected_count=0,
            failed_count=0,
        ),
        NewsRetrievalSourceOutcome(
            run=run,
            source_id="ecb_press",
            status="success",
            attempted_count=1,
            fetched_count=1,
            accepted_count=1,
            inserted_count=1,
            duplicate_count=0,
            rejected_count=0,
            failed_count=0,
        ),
    ])
    with pytest.raises(IntegrityError):
        await async_session.commit()
```

The migration test must upgrade a populated pre-Phase-3 database, assert safe defaults on
existing raw rows, insert a run/outcome, downgrade to `f7b8c9_terminal_enrichment`, and verify
the original raw row survives.

- [ ] **Step 2: Run tests and confirm schema failures**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_models.py tests/integration/test_retrieval_audit_migration.py -v`

Expected: failures identify absent fields/tables/revision.

- [ ] **Step 3: Implement additive models and migration**

Use JSON lists with `default=list`, UTC-naive timestamps consistent with the current schema,
foreign-key cascade from outcome to run, indexes on `(status, lease_expires_at)`,
`(source_id, started_at)`, and raw `source_id`. Existing raw rows receive nullable provenance;
new registry-backed records require it at the persistence boundary rather than through a
database check that would reject legacy API-provider rows.

- [ ] **Step 4: Run model, migration, and static checks**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_models.py tests/integration/test_retrieval_audit_migration.py -v`

Expected: all pass.

Run: `DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase3-task2.db .venv/bin/alembic upgrade head && .venv/bin/alembic heads`

Expected: upgrade succeeds and exactly `f8c9d0_add_retrieval_source_audit (head)` is printed.

- [ ] **Step 5: Commit Task 2**

```bash
git add shared/procuresignal/models shared/procuresignal/retrieval/base.py migrations/versions/f8c9d0_add_retrieval_source_audit.py tests/unit/test_models.py tests/integration/test_retrieval_audit_migration.py
git commit -m "Persist retrieval provenance and audit runs"
```

---

### Task 3: Safe Fetching, Retry Classification, And Circuits

**Files:**
- Create: `shared/procuresignal/retrieval/security.py`
- Create: `shared/procuresignal/retrieval/fetching.py`
- Create: `shared/procuresignal/retrieval/audit.py`
- Create: `tests/unit/test_retrieval_security.py`
- Create: `tests/unit/test_retrieval_fetching.py`
- Create: `tests/unit/test_retrieval_audit.py`
- Modify: `shared/procuresignal/retrieval/base.py`

**Interfaces:**
- Produces `URLSafetyPolicy.validate(url, allowed_hosts) -> ValidatedURL`.
- Produces `SafeFetcher.fetch(source: SourceDefinition) -> FetchResult` and `FetchFailureCode`.
- Produces `RetrievalAuditRepository.claim_run`, `claim_source`, `complete_source`,
  `fail_source`, and `complete_run`.

- [ ] **Step 1: Write failing SSRF and bounded-response tests**

```python
@pytest.mark.parametrize("url", [
    "http://official.example/feed",
    "https://user:pass@official.example/feed",
    "https://127.0.0.1/feed",
    "https://169.254.169.254/latest/meta-data",
])
async def test_url_policy_rejects_unsafe_destinations(url: str) -> None:
    with pytest.raises(UnsafeURL):
        await policy.validate(url, ("official.example",))


async def test_fetcher_stops_before_response_exceeds_five_mib(respx_mock) -> None:
    respx_mock.get(FEED_URL).mock(return_value=httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1)))
    result = await fetcher.fetch(source)
    assert result.failure_code is FetchFailureCode.OVERSIZED_RESPONSE
```

Mock DNS results explicitly so tests cover public, private, link-local, loopback, IPv4-mapped
IPv6, and redirect host changes without public DNS.

- [ ] **Step 2: Write failing retry/circuit/claim tests**

Assert 429 `Retry-After`, transient 503 retries, deterministic content-type failures without
retry, circuit opening on the fifth consecutive failure, half-open eligibility, success reset,
and two-session claim races yielding one owner. Assert exception messages and response bodies
are absent from persisted outcome details.

- [ ] **Step 3: Run focused tests and observe missing interfaces**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_retrieval_security.py tests/unit/test_retrieval_fetching.py tests/unit/test_retrieval_audit.py -v`

Expected: collection fails for the new modules.

- [ ] **Step 4: Implement safe fetch and durable audit state**

Read response bodies through `aiter_bytes()` while counting decoded bytes. Validate the initial
URL and every redirect before following it. Use structured failure enums. `claim_run` performs
a PostgreSQL `FOR UPDATE SKIP LOCKED` candidate read plus an owner/expiry conditional update;
SQLite relies on the conditional update's row count. Commit claims before network work. Do not
hold a row lock while fetching.

- [ ] **Step 5: Run focused tests and static checks**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_retrieval_security.py tests/unit/test_retrieval_fetching.py tests/unit/test_retrieval_audit.py -v`

Expected: all pass, including two-session claims and stale-lease recovery.

Run: `.venv/bin/black --check shared/procuresignal/retrieval tests/unit/test_retrieval_*.py && .venv/bin/ruff check shared/procuresignal/retrieval tests/unit && .venv/bin/mypy shared/procuresignal/retrieval`

Expected: all succeed.

- [ ] **Step 6: Commit Task 3**

```bash
git add shared/procuresignal/retrieval tests/unit/test_retrieval_security.py tests/unit/test_retrieval_fetching.py tests/unit/test_retrieval_audit.py
git commit -m "Add safe source fetching and durable circuits"
```

---

### Task 4: Registry-Driven RSS/Atom And In-Run Deduplication

**Files:**
- Create: `shared/procuresignal/retrieval/deduplication.py`
- Create: `tests/fixtures/retrieval/ecb_press.xml`
- Create: `tests/fixtures/retrieval/eu_commission_press.xml`
- Create: `tests/fixtures/retrieval/europe_logistics.xml`
- Create: `tests/fixtures/retrieval/europe_commodities.xml`
- Create: `tests/unit/test_rss_contracts.py`
- Create: `tests/unit/test_retrieval_deduplication.py`
- Modify: `shared/procuresignal/retrieval/providers/rss.py`
- Modify: `tests/unit/test_retrieval.py`

**Interfaces:**
- `RSSProvider(source: SourceDefinition, fetcher: SafeFetcher)` fetches exactly one source.
- `RSSProvider.fetch_articles(query_groups: list[str])` keeps interface compatibility but maps
  query group to the source's primary domain.
- `deduplicate_within_run(articles: Iterable[RawArticle]) -> DeduplicationResult` preserves the
  first highest-authority occurrence and records duplicate counts.

- [ ] **Step 1: Add recorded multilingual RSS/Atom contract fixtures and failing tests**

Fixtures must include RSS 2.0 and Atom, relative/absolute links, HTML summaries, stable IDs,
missing descriptions, timezone offsets, German/French entries, duplicate canonical URLs, and
one future timestamp. Tests assert complete registry metadata, sanitized bounded text, UTC
timestamps, source-specific domain assignment, and future timestamp capping.

- [ ] **Step 2: Add failing deterministic deduplication tests**

```python
def test_dedup_prefers_official_source_for_same_canonical_url() -> None:
    result = deduplicate_within_run([media_copy, official_item])
    assert result.articles == (official_item,)
    assert result.duplicates == 1


def test_content_fingerprint_collapses_tracking_url_variants() -> None:
    assert article_fingerprint(article_with_utm) == article_fingerprint(article_without_utm)
```

- [ ] **Step 3: Run tests and confirm old hard-coded provider fails**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_rss_contracts.py tests/unit/test_retrieval_deduplication.py tests/unit/test_retrieval.py -v`

Expected: constructor/metadata/dedup tests fail against `RSSProvider.FEEDS`.

- [ ] **Step 4: Implement one-source parsing and deterministic deduplication**

Remove `RSSProvider.FEEDS`. Do not add a compatibility alias for dead configuration. Parse
recorded bytes only after `SafeFetcher`; strip tags without executing or dereferencing markup.
Canonicalization removes fragments and known tracking parameters, normalizes host casing and
default ports, but does not reorder path segments or invent canonical URLs.

- [ ] **Step 5: Run focused and retrieval regression tests**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_rss_contracts.py tests/unit/test_retrieval_deduplication.py tests/unit/test_retrieval.py -v`

Expected: all pass and no test references `RSSProvider.FEEDS`.

- [ ] **Step 6: Commit Task 4**

```bash
git add shared/procuresignal/retrieval tests/fixtures/retrieval tests/unit/test_rss_contracts.py tests/unit/test_retrieval_deduplication.py tests/unit/test_retrieval.py
git commit -m "Replace hard-coded RSS feeds with source contracts"
```

---

### Task 5: Structured EU Sanctions Adapter

**Files:**
- Create: `shared/procuresignal/retrieval/providers/sanctions.py`
- Create: `tests/fixtures/retrieval/eu_financial_sanctions.xml`
- Create: `tests/fixtures/retrieval/eu_financial_sanctions_expected.json`
- Create: `tests/unit/test_sanctions_provider.py`
- Modify: `shared/procuresignal/retrieval/providers/__init__.py`
- Modify: `shared/procuresignal/retrieval/__init__.py`

**Interfaces:**
- Produces `EUSanctionsProvider(source: SourceDefinition, fetcher: SafeFetcher)`.
- Emits one `RawArticle` per stable designation/revision with `query_group="sanctions"`,
  `source_class="official"`, and official dataset provenance.

- [ ] **Step 1: Add immutable official-format fixture and failing parser tests**

Fixture cases must cover entity/person distinctions, aliases, multiple regulations, missing
optional remarks, XML namespaces, non-ASCII names, duplicate aliases, and two revisions of one
designation. Expected JSON stores stable IDs and exact normalized titles/descriptions; it is
independent of parser output.

- [ ] **Step 2: Add XML safety and identity tests**

Assert DOCTYPE/external-entity payload rejection, no network entity resolution, stable identity
across field order changes, distinct identity across official revision changes, and official
source URL retention.

- [ ] **Step 3: Run tests and observe missing provider**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_sanctions_provider.py -v`

Expected: collection fails because `EUSanctionsProvider` is absent.

- [ ] **Step 4: Implement the structured adapter**

Parse with a standard-library XML parser only after explicitly rejecting `<!DOCTYPE` and
`<!ENTITY` case-insensitively. Do not transform designations into compliance decisions; emit
factual designation/update records for later matching and risk-event logic. Never log the full
dataset or individual record bodies on failure.

- [ ] **Step 5: Run sanctions, security, and static checks**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_sanctions_provider.py tests/unit/test_retrieval_security.py -v`

Expected: all pass.

Run: `.venv/bin/ruff check shared/procuresignal/retrieval/providers/sanctions.py tests/unit/test_sanctions_provider.py && .venv/bin/mypy shared/procuresignal/retrieval/providers/sanctions.py`

Expected: both succeed.

- [ ] **Step 6: Commit Task 5**

```bash
git add shared/procuresignal/retrieval/providers tests/fixtures/retrieval/eu_financial_sanctions* tests/unit/test_sanctions_provider.py shared/procuresignal/retrieval/__init__.py
git commit -m "Ingest official EU sanctions designations"
```

---

### Task 6: Orchestration, Persistence, Claims, And Worker Metrics

**Files:**
- Create: `shared/procuresignal/retrieval/orchestrator.py`
- Create: `tests/unit/test_retrieval_orchestrator.py`
- Modify: `shared/procuresignal/retrieval/persistence.py`
- Modify: `worker/tasks.py`
- Modify: `tests/unit/test_tasks.py`
- Modify: `tests/integration/test_api.py`

**Interfaces:**
- Produces `RetrievalOrchestrator.run(run_key: str) -> RetrievalRunResult`.
- `RetrievalRunResult` exposes legacy totals plus `run_id`, `registry_version`, per-source
  results, rejection reasons, response bytes, latency, circuit state, and next poll time.
- `retrieve_news_task` retains `status`, `articles_fetched`, `articles_inserted`, `duplicates`,
  `errors`, `providers`, and `timestamp` keys.

- [ ] **Step 1: Write failing partial-failure and bounded-concurrency tests**

Use fake providers guarded by counters. Assert at most six total and two same-host fetches run
simultaneously; one timeout and one parser failure do not prevent successful sources from being
persisted; all clients close exactly once.

- [ ] **Step 2: Write failing run-claim and rerun-idempotency tests**

Two sessions/tasks with the same scheduled `run_key` must produce one acquired run and one
`already_running`/`already_completed` result. A stale 65-minute lease is reclaimable. Two
different run keys may execute. A rerun after completion inserts zero duplicate raw rows.

- [ ] **Step 3: Write failing provenance persistence tests**

Assert every registry-backed raw row persists source ID/class/domains/countries/version and
retrieval timestamp. Verify persistence uses savepoints or bulk conflict handling so one bad
row cannot roll back successful sources. Assert within-run duplicates and database duplicates
are separate counters.

- [ ] **Step 4: Run focused tests and observe missing orchestrator/metrics**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py -k retrieval tests/integration/test_api.py -k retrieval -v`

Expected: failures identify the missing orchestrator and audit metrics.

- [ ] **Step 5: Implement orchestration and worker integration**

Instantiate providers from registry definitions; use `asyncio.Semaphore(6)` globally and one
`Semaphore(2)` per hostname. Commit durable run/source claims before requests. Complete every
source outcome in a short transaction after fetch/persistence. Redact exception details into
failure enums. Preserve existing NewsAPI and optional GDELT toggles as registry/provider
configuration, not a second orchestration path.

- [ ] **Step 6: Run focused and full retrieval tests**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/unit/test_retrieval*.py tests/unit/test_tasks.py tests/integration/test_api.py -v`

Expected: all pass with legacy and additive worker metrics.

- [ ] **Step 7: Commit Task 6**

```bash
git add shared/procuresignal/retrieval worker/tasks.py tests/unit/test_retrieval_orchestrator.py tests/unit/test_tasks.py tests/integration/test_api.py
git commit -m "Orchestrate auditable multi-source retrieval"
```

---

### Task 7: Coverage Evaluation, Full Verification, And Phase Report

**Files:**
- Create: `tests/integration/test_retrieval_coverage.py`
- Create: `docs/superpowers/reports/2026-07-13-authoritative-procurement-sources.md`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces the deterministic Phase 3 coverage gate and operational documentation.
- Does not change public API/frontend response schemas.

- [ ] **Step 1: Write the failing end-to-end coverage test**

The test loads the production registry and all recorded fixtures, runs the real orchestrator
against mocked HTTP, persists results to SQLite, reruns the same run/input, and asserts:

```python
assert coverage.missing_domains == ()
assert coverage.missing_authoritative_domains == ()
assert result.llm_calls == 0
assert result.sources_succeeded >= 1
assert result.sources_failed >= 1  # recorded partial-failure case
assert rerun.articles_inserted == 0
assert all(row.source_id and row.registry_version for row in persisted_rows)
```

Also patch every OpenAI factory/import boundary to raise if invoked.

- [ ] **Step 2: Run the coverage test and close only genuine integration gaps**

Run: `PYTHONPATH=shared .venv/bin/pytest tests/integration/test_retrieval_coverage.py -v`

Expected before final wiring: FAIL on missing metrics or persistence integration. Implement only
the wiring required by the approved design, then rerun to PASS.

- [ ] **Step 3: Document configuration and source decisions**

README and `.env.example` must describe registry version, per-source enable overrides, GDELT
opt-in, safe-fetch limits, and offline test behavior without listing secrets. Compose must pass
the relevant environment values explicitly. The completion report must include:

- enabled source matrix and authority/domain/language coverage;
- endpoint ownership and usage verification date;
- rejected candidates with concrete reason;
- deterministic fixture inventory;
- fetched/accepted/deduplicated example metrics;
- partial-failure and two-worker claim evidence;
- zero-LLM assertion;
- migration and compatibility evidence;
- live-endpoint limitations and operational rollout steps.

- [ ] **Step 4: Run backend, migrations, frontend, and Compose gates**

Run: `PYTHONPATH=shared .venv/bin/pytest tests -q`

Expected: all backend tests pass.

Run: `.venv/bin/black --check . && .venv/bin/ruff check . && .venv/bin/mypy api worker shared`

Expected: all succeed.

Run: `DATABASE_URL=sqlite+aiosqlite:////tmp/procuresignal-phase3-final.db .venv/bin/alembic upgrade head && .venv/bin/alembic heads`

Expected: fresh upgrade succeeds with exactly one head. Then downgrade to
`f7b8c9_terminal_enrichment` and re-upgrade to head using a populated migration fixture.

Run: `cd frontend && npm run lint && npm run typecheck && npm run test:run && npm run build`

Expected: lint/typecheck/build succeed and all frontend tests pass.

Run: `docker compose config --quiet && git diff --check`

Expected: both succeed.

- [ ] **Step 5: Scan for stale configuration and incomplete documentation**

Run: `rg -n "RSSProvider\.FEEDS|feeds\.reuters\.com|TBD|TODO|FIXME" shared worker tests README.md .env.example docs/superpowers/reports/2026-07-13-authoritative-procurement-sources.md`

Expected: no dead hard-coded feed references or incomplete markers. Any intentional TODO in
unrelated legacy code must be listed explicitly rather than silently accepted.

- [ ] **Step 6: Commit Task 7**

```bash
git add tests/integration/test_retrieval_coverage.py docs/superpowers/reports/2026-07-13-authoritative-procurement-sources.md README.md .env.example docker-compose.yml
git commit -m "Verify authoritative procurement source coverage"
```

## Final Review Gate

After all seven tasks:

1. Generate a whole-branch diff from the plan base.
2. Request independent review for security, SSRF/DNS rebinding, XML safety, source licensing,
   migration reversibility, run/source concurrency, retry storms, metric cardinality, raw
   provenance, deduplication correctness, zero-LLM behavior, API compatibility, dead code, and
   accuracy of the completion report.
3. Fix every Important or Critical finding with a regression test and repeat review until
   approved.
4. Run the complete verification commands again from a clean worktree.
5. Merge locally into `main`, verify `main`, remove the merged worktree/branch, and do not push
   unless the user explicitly requests it.
