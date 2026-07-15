# Task 5 Report: Structured EU Sanctions Adapter

## Status

**BLOCKED.** No adapter, fixture, catalog enablement, or registry-coverage claim was added.
The official structured distribution is real and reachable with its published query token, but
it is not deployable through ProcureSignal's existing Task 3 retrieval boundary: the live XML is
24,730,335 bytes and `SafeFetcher` has a security-enforced 5 MiB decoded-response ceiling. The
tokenless registry URL also remains forbidden, and the registry/fetcher contract has no secret
query-parameter injection mechanism. Raising the global ceiling or embedding a token would
weaken or bypass the constraints in the amended brief.

## Official primary-owner verification (2026-07-15)

Ownership and distribution metadata were verified from the official data.europa.eu catalog API:

- Catalog query: `https://data.europa.eu/api/hub/search/search?q=consolidated%20list%20financial%20sanctions&limit=5`
- Current dataset ID: `consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions`
- Publisher: Directorate-General for Financial Stability, Financial Services and Capital Markets
  Union (DG FISMA), resource identifier
  `http://publications.europa.eu/resource/authority/corporate-body/FISMA`
- Dataset access right: `PUBLIC`
- XML 1.1 distribution ID: `5a1720a6-4ce5-4e09-ac97-6d120c09c799`
- Distribution title/format/media type: `Consolidated Financial Sanctions File 1.1`, XML,
  `application/xml`
- Supported endpoint shape:
  `https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=<access-token>`
- Authentication/access requirement: a query token is required by the current download service.
  The catalog supplies one, but the value is intentionally not copied into the repository,
  registry, fixtures, report, or command evidence.
- Commission ownership corroboration:
  `https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures/overview-sanctions-and-related-resources_en`
  states that DG FISMA manages and updates the consolidated list and links the Financial
  Sanctions Files service.

Live checks on 2026-07-15:

| Request | HTTP status | Observed content type | Observed size | Other evidence |
| --- | ---: | --- | ---: | --- |
| Tokenless XML 1.1 registry endpoint | 403 | `application/json` | 155 bytes | JSON `Forbidden` response |
| Exact catalog distribution URL, token supplied only at request time | 200 | `application/xml` | 24,730,335 bytes | `Last-Modified: Fri, 05 Jun 2026 14:00:13 GMT`; attachment filename `20260605-FULL-1_1(xsd).xml` |
| Financial Sanctions Files landing page through the documentation reader | 401 | unavailable | unavailable | Confirms the interactive service itself is access-controlled |

The live body began with an XML declaration and a namespaced `export` root. No dataset body or
individual designation was logged or committed.

## Exhausted supported paths

- The current official data.europa.eu dataset was inspected, including all ten published
  distributions. XML 1.0 and XML 1.1 both use the same token-bearing Webgate service; the CSV
  alternatives do as well. PDF and HTML are not structured designation distributions suitable
  for this adapter.
- The deprecated official catalog record was also inspected. It uses the same token-bearing
  Webgate distribution family and does not provide a distinct anonymous structured path.
- The current DG FISMA overview links the Webgate consolidated-list service but documents no
  ProcureSignal-ready API credential flow or alternate anonymous structured endpoint.
- The catalog's XML 1.1 URL was tested successfully without persisting the token. Removing its
  query token reproduced HTTP 403.

## Exact blockers

1. `SafeFetcher.__init__` clamps every response bound with
   `min(max_response_bytes, 5 * 1024 * 1024)`. Task 3's report explicitly records this as a
   security guarantee. The current official XML is approximately 4.72 times that hard limit and
   would deterministically return `OVERSIZED_RESPONSE` before parsing.
2. `SourceDefinition.endpoint_url` is a static URL and `SafeFetcher.fetch()` supplies no
   credential/header/query-secret resolver. Enabling the tokenless definition would therefore
   keep returning 403.
3. The amended brief prohibits copying a token into registry entries or fixtures. Doing so would
   also expose an access value in source control.
4. Raising the global Task 3 limit to admit this one dataset would weaken an approved retrieval
   security boundary. Implementing a parser behind an unreachable fetch path would falsely claim
   deployability and structured sanctions coverage.

## Required prerequisite to unblock

Add and separately security-review a source-scoped large-object ingestion design that preserves
bounded memory/disk use and SafeFetcher's DNS pinning, redirect, timeout, content-type, and circuit
guarantees. It must also provide secret-backed query-token injection without including the token
in `SourceDefinition`, logs, fixtures, snapshots, audit details, or final URLs. Only after that
boundary exists should Task 5 enable the source and implement the XML adapter test-first.

## Repository impact

- Preserved `missing_structured_authoritative_domains == (ProcurementDomain.SANCTIONS,)`.
- Left `eu_financial_sanctions` disabled and retained the known tokenless endpoint as 403.
- Did not create a misleading official-format fixture or parser for a source the runtime cannot
  retrieve.
- Did not modify the interview document.
