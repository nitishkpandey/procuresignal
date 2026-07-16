# Phase 3 Authoritative Procurement Sources

## Decision and coverage status

The production registry is `sources-v1`. Enabled sources cover every procurement domain, and the
mandatory sanctions/regulation domains have official announcement coverage. Structured
authoritative sanctions coverage is intentionally and explicitly missing. On 2026-07-15 the
official DG FISMA XML distribution required a query token and returned 24,730,335 bytes, while the
reviewed safe-fetch ceiling is 5 MiB. The tokenless URL returned HTTP 403. No token is stored here,
the global ceiling was not raised, and no synthetic sanctions fixture or deployability claim was
created.

## Enabled source matrix

| Source | Class | Domains | Country / language | Default |
| --- | --- | --- | --- | --- |
| European Commission Press Corner | official | sanctions, regulation, logistics, commodities, supplier risk, Europe business | EU / en | enabled |
| European Central Bank Press | official | FX, regulation, Europe business | EU / en | enabled |
| Eurostat Data Updates | official | logistics, commodities, supplier risk, Europe business | EU / en | enabled |
| MINING.COM | industry | commodities, supplier risk | CA / en | enabled |
| Oilprice.com | industry | commodities, logistics, supplier risk | GB / en | enabled |
| Supply Chain Dive | industry | logistics, supplier risk, Europe business | US / en | enabled |
| Deutsche Welle Business | established media | regulation, commodities, supplier risk, Europe business | DE / en | enabled |

`SOURCE_<SOURCE_ID>_ENABLED=true|false` explicitly overrides any catalog default. NewsAPI is added
only when `NEWSAPI_KEY` is supplied. GDELT is an explicit opt-in through `GDELT_ENABLED=true`.

## Endpoint ownership and review

Endpoint ownership, public access behavior, content type, terms/attribution note, and final status
were reviewed on 2026-07-13 for all registry candidates. DG FISMA ownership and its current
token-bearing data.europa.eu distribution were reverified on 2026-07-15. The registry retains
publisher homepage, endpoint, host allowlist, authority class, country/language, polling interval,
item bound, trust seed, and license note as immutable provenance.

Rejected or disabled candidates:

- Council of the EU press RSS returned HTTP 403 during review.
- EU Financial Sanctions Files requires secret query injection and is approximately 4.72 times
  the reviewed response bound.
- FreightWaves publisher terms limit site content to personal use without permission.
- GDELT is broad secondary event data and therefore remains opt-in.

## Deterministic evaluation

The offline integration gate uses all four immutable recorded feeds: `ecb_press.xml`,
`eu_commission_press.xml`, `europe_commodities.xml`, and `europe_logistics.xml`. They cover RSS and
Atom, German and French metadata, relative and absolute links, HTML text, tracking parameters,
timezone offsets, missing descriptions, and future dates. Every enabled registry source runs
through the real orchestrator and RSS parser with mocked HTTP; one source returns a structured
HTTP-status failure.

The representative run fetches nine feed records from six successful sources. Eight unique
records are inserted and one within-run duplicate is removed; the seventh source fails in isolation. Repeating
the identical run key inserts zero records. All persisted rows carry `source_id` and
`registry_version`. The gate poisons imported OpenAI construction boundaries and asserts zero LLM
calls.

## Concurrency, migration, and compatibility evidence

Task 6 tests demonstrate a global concurrency ceiling of six, a per-host ceiling of two,
partial-failure isolation, and exactly one durable owner when two workers race for the same run or
source claim. Stale leases recover atomically. Migration verification covers a fresh upgrade,
exactly one head, a populated downgrade to `f7b8c9_terminal_enrichment`, and re-upgrade. Retrieval
metrics are additive internal result properties; no REST, WebSocket, or frontend schema changed.

## Operational rollout

1. Start from the checked-in defaults and enable only reviewed sources permitted for the
   deployment's usage context.
2. Supply NewsAPI credentials through the secret store, never a registry URL; opt into GDELT only
   after considering volume and relevance.
3. Observe per-source outcomes, failure codes, response bytes, circuits, latency, and next poll
   time before widening rollout.
4. Keep the 5 MiB, retry, redirect, timeout, HTTPS, allowlist, and DNS-pinning boundaries intact.
5. Treat structured sanctions as unavailable until a separately reviewed source-scoped streamed
   large-object path and secret-backed query injection mechanism exist.

Live endpoints are not exercised by CI and can change availability, payload shape, or terms after
the verification dates. Operators must reverify ownership and usage conditions before enabling a
disabled source.
