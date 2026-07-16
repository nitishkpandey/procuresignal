# Phase 3: Authoritative Procurement Sources Design

## Status

Approved design for Phase 3 of ProcureSignal. This phase expands retrieval coverage while
preserving the cost controls, idempotency, and auditability established in Phase 2.

## Goal

Make the feed materially more complete and procurement-relevant by adding maintainable
European business, regulatory, sanctions, logistics, commodity, FX, and supplier-risk
sources. Prefer authoritative sources and explicit provenance over indiscriminate volume.

## Non-Goals

- Preference-generated supplier queries belong to Phase 4.
- Learned source-confidence and relevance models belong to Phase 5.
- Autonomous monitoring decisions and actions belong to Phase 6.
- A search index, embeddings, scraping paywalled pages, and browser automation are out of
  scope.
- Retrieval must not introduce an LLM call.

## Design Principles

1. **Authority first.** Official regulatory and sanctions sources are the primary record for
   legal or compliance events. Established media and industry sources add timeliness and
   operational context but never replace primary provenance.
2. **Configuration over duplication.** Compatible RSS/Atom feeds use one generic provider
   driven by a typed registry. A dedicated adapter is justified only when a structured source
   has semantics that RSS cannot preserve.
3. **Fail independently.** One unavailable, malformed, or rate-limited source does not fail a
   retrieval run.
4. **Retain provenance.** Every raw record identifies the configured source, authority class,
   procurement domains, language, geography, registry version, and retrieval timestamp.
5. **Deterministic and idempotent.** Source parsing, validation, deduplication, and persistence
   are deterministic and testable without network access.
6. **Safe by construction.** Only registry URLs with HTTPS and approved hostnames are fetched.
   Redirects are bounded and revalidated. Feed markup is treated as untrusted data.

## Architecture

### Source Registry

Create a versioned, typed registry in the shared retrieval package. Each `SourceDefinition`
contains:

- stable `source_id`;
- display name and canonical homepage;
- adapter type (`rss`, `structured_sanctions`, or an existing API provider);
- source class (`official`, `established_media`, `industry`);
- procurement domains;
- countries/regions and content languages;
- feed or endpoint URL;
- polling cadence and per-poll item limit;
- enabled-by-default flag;
- expected content type and optional parser hints;
- trust seed used only as source metadata until Phase 5;
- license/usage note and registry version.

Registry loading must fail fast for duplicate IDs, non-HTTPS endpoints, unsupported adapter
types, empty domain/language sets, invalid trust values, unsafe hosts, or item limits outside
the configured bound. Environment configuration may enable or disable registered sources but
must not inject arbitrary URLs.

### Provider Boundaries

Retain the existing `NewsProvider` interface. Replace the hard-coded `RSSProvider.FEEDS`
mapping with registry-selected definitions. The RSS adapter fetches a single definition at a
time, so source attribution and failure metrics cannot be confused across feeds.

Use a dedicated structured sanctions adapter for an official EU consolidated dataset. It
emits deterministic procurement-risk records with the official dataset URL and update time;
it must not pretend that a sanctions designation is an ordinary publisher article. A stable
designation identity and dataset revision form its provider identity. Records still enter the
raw store so lineage and downstream handling remain consistent.

NewsAPI and optional GDELT remain supported. Their results receive explicit aggregator source
metadata and cannot claim `official` authority merely because an underlying publisher name is
present.

### Raw Metadata

Extend `RawArticle` and `news_articles_raw` with additive retrieval metadata:

- `source_id`;
- `source_class`;
- `source_domains` as a normalized JSON list;
- `source_countries` as a normalized JSON list;
- `registry_version`;
- `retrieved_at`;
- optional `source_published_at_raw` for audit/debugging.

Existing API and frontend contracts do not change. Existing rows and API-provider records get
safe defaults through the migration and adapter boundary.

## Initial Coverage Matrix

The committed catalog must satisfy this minimum matrix. A source is included only after its
endpoint, ownership, usage terms, and recorded fixture have been verified during
implementation.

| Domain | Required authoritative coverage | Required contextual coverage |
|---|---|---|
| EU regulation and trade | European Commission and/or EUR-Lex official updates | One established European business source |
| Sanctions | European Commission/DG FISMA consolidated sanctions data or EU Sanctions Map data | Council/Commission sanctions announcements |
| FX and monetary policy | ECB official RSS/data communication | Existing Frankfurter monitor remains separate |
| Logistics disruption | Official European transport or maritime notices where a stable public feed exists | At least two established logistics/industry feeds |
| Commodities and industrial inputs | Official EU/European statistical or market communication where a stable feed exists | At least two established commodity/industry feeds |
| Supplier and European business risk | Official company/regulatory announcements where reusable feeds exist | At least two established European business/industry feeds |

Every required procurement domain must have two independent configured sources where
practical, and sanctions and regulation must each include at least one authoritative source.
If a candidate endpoint lacks a stable public machine-readable interface or compatible usage
terms, the implementation report must reject it explicitly rather than add brittle scraping.

## Retrieval Flow

1. The scheduled task creates one retrieval run identifier.
2. The registry selects enabled sources that are due for polling.
3. Sources are fetched concurrently with a small global bound and a stricter per-host bound.
4. Each request applies a connect/read timeout, maximum response size, content-type check,
   bounded redirects, and retry policy.
5. The adapter parses items into `RawArticle` values with complete registry metadata.
6. Invalid items are rejected with reason codes before persistence.
7. Canonical URL and normalized content fingerprints deduplicate within the run.
8. The existing database ingest hash remains the final cross-run idempotency boundary.
9. Per-source outcomes are persisted with the retrieval run and returned in worker metrics.
10. All provider clients close even when another provider fails.

Concurrency must not allow two scheduler instances to create duplicate retrieval work. Use a
database-backed run/lease boundary or an equivalently durable claim. Process-local locks are
not sufficient.

## Failure And Backoff Semantics

Classify failures as `timeout`, `rate_limited`, `http_error`, `unsafe_redirect`,
`oversized_response`, `invalid_content_type`, `parse_error`, or `persistence_error`.

- Respect valid `Retry-After` values within a configured maximum.
- Apply bounded exponential backoff with jitter for transient network/5xx failures.
- Do not retry deterministic parser, content-type, or registry validation failures in the same
  run.
- Open a durable per-source circuit after repeated consecutive failures. A half-open probe
  becomes due after the cooldown; one success closes the circuit.
- Never expose credentials, response bodies, or full query strings in error metrics.
- A partially successful run is successful-with-errors, not globally failed.

## Security And Data Handling

- Only HTTPS endpoints on the registry allowlist may be requested.
- Re-resolve and validate redirect destinations; reject credentials in URLs and non-public
  address targets to reduce SSRF risk.
- Enforce response byte limits before parsing.
- Strip active markup; store only bounded text fields and the existing JSON-safe raw payload.
- Treat feed titles, descriptions, links, and dataset fields as untrusted input.
- Do not execute embedded HTML, JavaScript, XML external entities, or remote stylesheet/media
  references.
- Validate all persisted URLs and timestamps; cap future publication timestamps.

## Metrics And Auditability

Add per-source and total metrics without removing current worker result keys:

- attempted, fetched, accepted, inserted, duplicate, rejected, and failed counts;
- failure reason counts;
- latency and response bytes;
- source circuit state and next eligible poll time;
- registry version and retrieval run ID.

Persist a retrieval-run audit row and per-source outcome rows. Metrics cardinality must use
stable registry IDs, not article titles, URLs, or arbitrary exception strings.

## Testing Strategy

Implementation follows test-driven development.

### Unit And Contract Tests

- registry validation and deterministic selection;
- RSS/Atom parsing for multilingual fixtures and missing optional fields;
- official sanctions dataset parsing and stable identities;
- metadata propagation into `RawArticle`;
- canonical URL and in-run content deduplication;
- timeout, rate-limit, redirect, content-type, response-size, and parser classifications;
- retry/backoff and circuit-state transitions;
- HTML/XML safety behavior.

### Integration Tests

- recorded HTTP fixtures only; CI must not require public internet or API keys;
- partial provider failure with successful persistence from other sources;
- retrieval-run and per-source audit persistence;
- database idempotency across reruns;
- two-worker durable claim behavior;
- schema upgrade/downgrade with populated data;
- unchanged feed API/frontend contracts.

### Coverage Gate

A deterministic test reads the committed registry and proves:

- every Phase 3 domain appears in the registry;
- sanctions and regulation include an authoritative source;
- sanctions include an enabled official `structured_sanctions` source; official announcement
  feeds count as sanctions news authority but do not satisfy this structured-data requirement;
- two independent sources exist per domain where the matrix requires them;
- enabled sources have recorded parser fixtures;
- no enabled source uses plain HTTP, an unapproved hostname, or unknown licensing status;
- no retrieval path invokes OpenAI.

Optional live smoke tests may check enabled public endpoints manually or on a separate
scheduled workflow. They are diagnostic and never replace recorded contract fixtures.

## Compatibility And Rollout

1. Add registry and metadata contracts with defaults.
2. Migrate raw metadata and retrieval audit tables.
3. Move RSS feeds into the registry while preserving provider identity compatibility.
4. Add authoritative and contextual sources in small reviewed groups.
5. Add the structured sanctions adapter.
6. Wire bounded concurrency, durable source state, and worker metrics.
7. Run the complete backend/frontend/migration/Compose gates.

The feature can be disabled per source. Existing NewsAPI/GDELT behavior remains available.
Rollback disables new sources first; schema downgrade remains supported while Phase 3 data is
still within the retention window.

## Completion Criteria

Phase 3 is complete only when:

- the registry and initial coverage matrix pass deterministic validation;
- all enabled feeds/adapters have recorded contract fixtures;
- authoritative sanctions and regulation coverage is implemented;
- European business, logistics, commodity, FX, and supplier-risk coverage meets the matrix;
- provenance metadata and retrieval audit records persist correctly;
- partial failures, retries, circuits, deduplication, and concurrent runs are tested;
- no LLM is called during retrieval;
- existing API/frontend behavior remains compatible;
- backend tests, Black, Ruff, MyPy, frontend lint/typecheck/tests/build, migrations, Compose
  validation, and independent whole-branch review pass;
- limitations and rejected source candidates are documented in the Phase 3 completion report.
