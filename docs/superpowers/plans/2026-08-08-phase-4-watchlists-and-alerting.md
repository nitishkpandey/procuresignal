# Phase 4: Watchlists, Alert Rules and Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the feed into something that reaches a buyer without them opening it — the product
thesis is early warning, and a signal nobody sees is not one.

**Architecture:** Organization-scoped watchlists over canonical suppliers, alert rules evaluated
against risk events, and a notification outbox with pluggable transports. In-app delivery ships
first; email is one more transport behind the same interface, added when credentials exist.

**Tech Stack:** SQLAlchemy async, Alembic, FastAPI, Celery, Next.js 16, Vitest.

## Global Constraints

- Watchlists are **organization**-scoped, not user-scoped. A team watches a supplier together;
  per-user lists fragment the thing the team is trying to share.
- Watchlists reference `suppliers.public_id`. Free-text watchlists would reinherit every miss
  Phase 2 removed.
- Delivery is at-least-once with idempotent dedup, never at-most-once. A missed disruption alert
  is the failure this product exists to prevent; a duplicate is an annoyance.
- The outbox records **why** a notification was sent — which rule, which event, which supplier.
  An alert a buyer cannot trace back is one they learn to ignore.
- Every mutation is audited via `record_audit` and role-gated: viewers read, members write.
- No transport may block evaluation. A failing transport retries from the outbox; it never stalls
  the rule that produced the notification.
- Backend gate per task: `pytest tests/ -q --no-cov`, `black --check .`, `ruff check .`,
  `mypy api worker shared`. Frontend tasks additionally run tests, typecheck, lint, build, and
  `verify:routes`.

## Why watchlists come first

Notification rules need something to watch. Supplier profiles need something to show. Digests need
something to summarise. All three key off a stable, organization-scoped membership boundary, and
building any of them on a per-user or free-text list means rewriting all three later — the same
fan-out argument that put auth first in Phase 1 and supplier identity first in Phase 2.

## File Structure

- `shared/procuresignal/models/watchlists.py`: `Watchlist`, `WatchlistEntry`.
- `shared/procuresignal/models/notifications.py`: `AlertRule`, `Notification`.
- `shared/procuresignal/watchlists/service.py`: create, add, remove, list.
- `shared/procuresignal/notifications/rules.py`: evaluation against risk events.
- `shared/procuresignal/notifications/outbox.py`: enqueue, dedup, mark delivered.
- `shared/procuresignal/notifications/transports/`: `InAppTransport`, later `EmailTransport`.
- `api/routers/watchlists.py`, `api/routers/notifications.py`.
- `frontend/app/watchlists/`, `frontend/components/notification-bell.tsx`.

---

### Task 1: Watchlist schema and service

**Files:**
- Create: `shared/procuresignal/models/watchlists.py`, `shared/procuresignal/watchlists/service.py`
- Create: `migrations/versions/n8o9p0_watchlists.py` (down_revision `m7n8o9_llm_spend`)
- Test: `tests/unit/test_watchlists.py`

**Interfaces:**
- Produces: `Watchlist` (`public_id`, `organization_id`, `name`, `created_by_user_id`),
  `WatchlistEntry` (`watchlist_id`, `supplier_id`, `added_by_user_id`);
  `create_watchlist`, `add_supplier`, `remove_supplier`, `watched_supplier_ids`.

**Design notes:**

Unique on `(watchlist_id, supplier_id)` so adding twice is a no-op rather than a duplicate. Unique
on `(organization_id, name)` so a team cannot end up with two lists called "Tier 1" and wonder
which one alerts.

`watched_supplier_ids(session, organization_id)` returns canonical ids for the whole organization
in one query — it is what rule evaluation joins against, and a per-watchlist query would make
evaluation N+1 over rules.

Removing a supplier from the registry must not orphan entries: the FK cascades, and a test pins it.

- [ ] Step 1: Failing tests — org scoping, duplicate no-op, name uniqueness, cascade
- [ ] Step 2: Models, migration, service; verify migration and model agree
- [ ] Step 3: Full gate, commit

---

### Task 2: Watchlist API

**Files:**
- Create: `api/routers/watchlists.py`, `api/schemas/watchlist.py`
- Test: `tests/integration/test_watchlist_api.py`

**Interfaces:**
- Produces: `GET/POST /api/watchlists`, `GET /api/watchlists/{public_id}`,
  `POST/DELETE /api/watchlists/{public_id}/suppliers/{supplier_public_id}`.

**Design notes:**

Reads need a member; writes need a member; nothing here needs an admin, because watching a supplier
is ordinary work rather than administration.

A watchlist from another organization returns **404, not 403** — the same reasoning as conversation
messages in Phase 1: a 403 confirms the id exists.

- [ ] Step 1: Failing tests including cross-organization isolation
- [ ] Step 2: Implement, audit every mutation, full gate, commit

---

### Task 3: Alert rules

**Files:**
- Create: `shared/procuresignal/models/notifications.py`,
  `shared/procuresignal/notifications/rules.py`
- Test: `tests/unit/test_alert_rules_engine.py`

**Design notes:**

A rule is: for this organization, when a risk event touches a watched supplier, at or above this
severity, of these risk types, notify these recipients.

Evaluation reads `RiskEvent.affected_supplier_ids` — the column Phase 2 Task 6 added. Matching on
`affected_suppliers` text would reinherit the misses.

Rules are evaluated **after** risk events are generated, not inside the detector: a slow or broken
rule must not stop events being recorded.

- [ ] Step 1: Failing tests — severity threshold, type filter, watched-only, disabled rules
- [ ] Step 2: Implement, full gate, commit

---

### Task 4: Notification outbox

**Files:**
- Create: `shared/procuresignal/notifications/outbox.py`
- Test: `tests/unit/test_notification_outbox.py`

**Design notes:**

At-least-once with an idempotency key of `(rule_id, risk_event_id, recipient)`. Re-evaluating the
same event must not re-notify, and the constraint enforces that rather than a query-then-insert
race.

Rows carry `status`, `attempts`, `last_error`, and the provenance the buyer needs: rule, event,
supplier. Transport failures increment attempts and stay pending; they never raise into evaluation.

- [ ] Step 1: Failing tests — dedup, retry accounting, provenance, transport failure isolation
- [ ] Step 2: Implement, full gate, commit

---

### Task 5: In-app delivery and the notification API

**Files:**
- Create: `shared/procuresignal/notifications/transports/in_app.py`,
  `api/routers/notifications.py`
- Test: `tests/integration/test_notification_api.py`

**Interfaces:**
- Produces: `GET /api/notifications`, `POST /api/notifications/{public_id}/read`,
  `GET/POST /api/alert-rules`.

- [ ] Step 1: Failing tests including cross-tenant isolation on the feed of notifications
- [ ] Step 2: Implement, full gate, commit

---

### Task 6: Scheduled evaluation and delivery

**Files:**
- Modify: `worker/tasks.py`, `worker/celery_config.py`
- Test: `tests/unit/test_notification_tasks.py`

**Design notes:**

Two tasks: evaluate rules after risk events, and drain the outbox. Separate, so a transport outage
does not stop evaluation and a slow rule does not stop delivery of what is already queued.

Both report pipeline freshness, both are covered by the dead-letter path, and the outbox depth is a
metric so a stalled drain is visible rather than silent.

- [ ] Step 1: Failing tests — routing, scheduling, freshness, metrics
- [ ] Step 2: Implement, full gate, commit

---

### Task 7: Digest generation

**Files:**
- Create: `shared/procuresignal/notifications/digest.py`
- Test: `tests/unit/test_digest.py`

**Design notes:**

Generation is separable from delivery, which is what makes this shippable without SMTP. The digest
renders to a structure and to text; the email transport later just sends it.

Empty digests are not sent. A daily message saying nothing happened trains people to stop reading
the one that says something did.

- [ ] Step 1: Failing tests — grouping, empty suppression, per-organization scoping
- [ ] Step 2: Implement, full gate, commit

---

### Task 8: Watchlist and notification UI

**Files:**
- Create: `frontend/app/watchlists/page.tsx`, `frontend/components/watchlist-view.tsx`,
  `frontend/components/notification-bell.tsx`
- Test: `frontend/__tests__/watchlist-view.test.tsx`

**Design notes:**

Tests synchronise on loaded content, never on an element present during loading — the race that
turned CI red twice.

- [x] Step 1: Failing tests, implement, full frontend gate including `verify:routes`, commit, push

---

## Self-Review

**Ordering:** Task 3 needs Task 1's `watched_supplier_ids`. Task 4 needs Task 3's rules. Task 5
needs Task 4's outbox. Task 6 needs 3 and 4. Tasks 7 and 8 need 5. No task references anything
defined later.

**Deliberately out of scope:**

- **Email delivery.** One transport behind the interface Task 4 defines, added when SMTP
  credentials exist. Digest *generation* ships here so that is a small change rather than a phase.
- **Slack and Teams.** Same interface, gated on workspace tokens.
- **Supplier profile pages.** They read watchlists and risk events, so they follow naturally, but
  they are presentation and this phase is about the signal reaching someone.
- **Saved searches.** Closer to the feed than to alerting; better grouped with Phase 5's search
  work than bolted on here.
