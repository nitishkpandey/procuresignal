# ProcureSignal Production Readiness Roadmap

> **Scope:** This is the program-level roadmap and decision record. It locks architectural
> decisions and phase ordering. Each phase gets its own detailed executable plan in
> `docs/superpowers/plans/` written immediately before that phase begins, using
> `superpowers:writing-plans`. This document is the index; it is not itself executable.

**Goal:** Take ProcureSignal from a production-style prototype to a system that can serve real
European procurement customers, without pretending that unbuilt integrations exist.

**Source of requirements:** `docs/interview-preparation.md` §10 (Planned Add-On Features),
reinterpreted for production rather than demo delivery.

---

## 1. Decision Record

These decisions are locked. Changing one requires updating this section and re-checking every
phase that depends on it.

### D1 — Authentication: self-hosted, SSO-shaped

**Decision:** Email + password with argon2 hashing, JWT access tokens with refresh and
server-side revocation. Schema is `organizations` / `users` / `memberships` with role on
membership, designed so SSO and SCIM attach as adapters.

**Rejected:** Starting with a hosted IdP (Auth0/Okta/Entra).

**Why:** Enterprise procurement RFPs require SSO, so the *schema* must be SSO-shaped from day
one — retrofitting identity onto a live tenant model is the most expensive migration available.
But the IdP itself is an adapter behind `AuthProvider`. Building tenancy correctly is the design
problem; the IdP is a configuration problem, and it needs vendor accounts that do not yet exist.

### D2 — Notifications: one engine, pluggable transports

**Decision:** A single notification engine owning rules, deduplication, delivery log, and retry
with backoff. Transports implement `NotificationTransport`. In-app and email ship first with a
real SMTP/SendGrid transport. Slack and Teams are adapters added when workspace tokens exist.

**Rejected:** In-app-only delivery.

**Why:** The product thesis is early warning. In-app-only means the user learns about a supplier
disruption when they next log in, which is exactly the manual-monitoring behaviour the product
exists to replace. A morning email digest is the habit-forming surface in procurement tooling.
The engineering value is in the rules and delivery guarantees, none of which is Slack-specific.

### D3 — ERP integration: port plus mock adapter

**Decision:** Define `ProcurementSystemAdapter` with one working mock implementation.

**Rejected:** Building SAP Ariba / Coupa / Oracle / Workday adapters.

**Why:** Each requires a vendor sandbox, which requires a customer engagement. The integration
contract is designable now; the adapters are not implementable now. A mock proves the contract
and makes the first real adapter a day of work rather than a redesign.

### D4 — Vector search: pgvector

**Decision:** `pgvector` extension in the existing PostgreSQL instance.

**Rejected:** Pinecone, Weaviate, Qdrant, or any separate vector service.

**Why:** Corpus size is bounded by a 30-day retention policy. A dedicated vector service adds a
network hop, a second consistency domain, and an operational surface for a workload that fits
comfortably in Postgres. Revisit if corpus exceeds ~10M vectors or p99 search latency exceeds
200ms.

### D5 — Supplier master data: required foundation

**Decision:** A `suppliers` registry with canonical IDs, alias sets, country, and LEI where
available, plus a resolution layer mapping extracted text to canonical entities with a
confidence score and a manual override path. All downstream features key off supplier IDs.

**Why:** This is the highest-consequence gap in the current system. Suppliers today are
free-text strings extracted per article. "Siemens AG", "Siemens", "SIEMENS Aktiengesellschaft",
and "Siemens Energy" are four strings, two legal entities, and one spinoff with a distinct risk
profile. Without canonical IDs: watchlists silently miss events, impact scoring cannot aggregate
exposure, and **sanctions screening produces false negatives** — an EU compliance failure, not a
bug. This is why Phase 2 precedes every feature that consumes supplier identity.

### D6 — Agents: one reasoning loop, deterministic everything else

**Decision:** One tool-using agent loop for supplier impact analysis and mitigation
recommendation, with a human approval gate and a full audit trail. Monitoring, notification, and
approval remain deterministic code.

**Rejected:** The five-agent design in `docs/interview-preparation.md:484`.

**Why:** Of the five listed "agents", the monitor is a scheduled job, the notifier is a delivery
queue, and the approver is a state machine. Implementing deterministic pipeline stages as LLM
agents adds cost, latency, and nondeterminism while removing auditability — the opposite of what
procurement compliance requires. Only impact analysis and mitigation involve genuine
multi-step reasoning over heterogeneous evidence.

### D7 — Deferred infrastructure, with triggers

Not built now. Each has an explicit condition that would reopen the decision, so these are
deferred rather than forgotten.

| Deferred | Trigger to revisit |
|---|---|
| Kafka / Redpanda | Ingestion exceeds Celery+Redis throughput, or a second consumer needs the same event stream |
| OpenSearch / Elasticsearch | Postgres full-text p99 exceeds 500ms, or ranking needs BM25 tuning |
| Data lake / warehouse / dbt | A real analytics consumer exists (BI tool or customer-facing reporting) |
| Learning-to-rank model | Feedback table holds enough labelled interactions for a train/test split |
| Knowledge graph | Multi-tier supplier relationships become a product requirement |

Note: LTR is deferred but its **prerequisite is built** in Phase 5 — relevance feedback capture.
Collecting the data is the honest first step; a model trained on no data is a liability.

---

## 2. Production Concerns Not In The Feature Roadmap

`docs/interview-preparation.md` §10 is a feature list. These are not features, and their absence
is what distinguishes "production-style" from "production". Each is assigned to a phase.

### Legal and regulatory

| Concern | Phase | Note |
|---|---|---|
| Content licensing | **Blocked — owner decision** | NewsAPI's free tier is developer/non-commercial with delayed articles. Commercial production use requires a paid plan. Storing and redisplaying full RSS content has copyright limits. Architecture mitigates (snippet-only storage, attribution, link-out, per-source license metadata in the registry) but cannot grant rights. |
| GDPR | 7 | EU users, stored emails, retained third-party content. Requires processing records, enforced retention, DSAR export, right to erasure, documented lawful basis. |
| Data residency | Deferred to hosting | Must remain EU-capable; constrains hosting choice, which the owner has deferred. |

### Operational

| Concern | Phase | Why it matters here |
|---|---|---|
| Backups with tested restore | 8 | An untested backup is not a backup. |
| Rate limiting (per tenant, per IP) | 3 | |
| Per-tenant LLM budget caps | 3 | Enrichment cost scales with articles × tenants. One runaway ingestion loop is a five-figure surprise. Hard caps, not just monitoring. |
| Secrets management | 3 | `.env` does not scale past one host. (Hygiene is currently clean — `.env` was never committed.) |
| Alert rules, not just metrics | 3 | `/metrics` with no alerts is a dashboard nobody watches. **Pipeline freshness is the critical alert**: the classic failure is ingestion returning zero articles for days while every health check stays green. |
| Celery dead-letter queue | 3 | A poison message currently retries forever. |
| Token revocation | 1 | Logout that does not revoke is not logout. |
| Zero-downtime migrations | 3 | Expand/contract discipline; no destructive migration in a single deploy. |
| `pip-audit` + Dependabot | 3 | `bandit` covers our code, not our dependencies. |

---

## 3. Phase Order

Phases 1 and 2 are foundations. Everything after them keys off their schemas, which is why they
are sequenced by dependency fan-out rather than by product value.

| Phase | Deliverable | Depends on |
|---|---|---|
| **0** | Finish and merge bounded sanctions streaming | — |
| **1** | Auth, tenancy, RBAC, audit log, token revocation | — |
| **2** | Supplier master data + entity resolution | 1 |
| **3** | Platform hardening: `/metrics` + alert rules, frontend CI, CORS, rate limiting, DLQ, budget caps, dependency scanning | 1 |
| **4** | Watchlists, alert rules, saved searches, notification engine, email digest, supplier profiles | 1, 2 |
| **5** | pgvector semantic search, feedback capture, impact scoring, evaluation framework | 2 |
| **6** | Agent loop with human approval and audit trail | 2, 4 |
| **7** | GDPR: retention enforcement, DSAR export, erasure, processing records | 1 |
| **8** | Backup/restore runbook with tested restore, dashboards, SLOs | 3 |
| **9** | Dead code, DRY, stale comment sweep, unified `verify.sh` | all |

### Rationale for the two foundation phases

**Why auth first:** watchlists, alert rules, saved searches, audit logs, notification
preferences, and dashboards all key off user and organization. Built against the current
`user_id`-as-query-parameter model (`api/routers/feed.py:49`), every one requires new columns,
new migrations, new queries, and new tests when tenancy lands. Auth has the widest fan-out in
the dependency graph.

**Why supplier master data second:** see D5. Watchlists on free-text supplier names are watchlists
that silently fail.

---

## 4. Execution Discipline

**Per phase:** detailed plan → implementation with tests written alongside → full verification
gate → independent review → one commit → push to `main`.

**Not** batch-everything-then-verify. Large batches delay defect discovery rather than reducing
it. Phase 0 is the evidence: the sanctions implementation was reported complete and verified,
and independent review then found three critical defects — a token leak into httpx logs,
deduplication collapsing all designations into one record, and an orchestrator that never
invoked the new adapter. Found at review in a small batch; found after four dependent features
in a large one.

**Verification gate (every phase):**

```
pytest tests/ -q
black --check .
ruff check .
mypy api worker shared
cd frontend && npm run test:run && npm run typecheck && npm run lint && npm run build
```

Phase 9 collapses this into a single `verify.sh`.

**Commits:** human-readable subject lines describing intent, not mechanics. No AI attribution
trailers.

---

## 5. Open Items Requiring Owner Input

| Item | Status | Consequence if unresolved |
|---|---|---|
| Content licensing terms (NewsAPI plan, RSS redistribution) | **Blocking for commercial launch** | Architecture proceeds with snippet-only storage and per-source license metadata; rights cannot be engineered. |
| Target launch date | Not provided | Phases proceed in dependency order at full quality. A hard date changes what fits, not the quality bar. |
| Hosting platform | Deliberately deferred by owner | Constrains Phase 8 only. Must remain EU-residency-capable. |
| SMTP/SendGrid credentials | Needed for Phase 4 | Email transport ships behind the interface; digest cannot deliver without them. |
| Slack/Teams tokens | Optional | Adapters written when supplied. |
