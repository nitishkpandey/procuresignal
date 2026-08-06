# Phase 3a: Deployment Safety Net Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop defects reaching production silently. Nothing here is user-facing; every task
closes a path by which something broken ships or runs unnoticed.

**Architecture:** Six independent hardening tasks with no shared state, ordered cheapest-first so
each one protects the ones after it. No external accounts or credentials required.

**Tech Stack:** GitHub Actions, prometheus-client, Prometheus alert rules, Celery, FastAPI,
pip-audit, Dependabot.

## Global Constraints

- No user-facing behaviour changes. A feature test that starts failing means something is wrong.
- Metrics carry only bounded label values: source ids, task names, tenant public ids. Never
  article URLs, exception strings, tokens, or full query strings — the existing retrieval rule.
- `/metrics` is unauthenticated but must expose no tenant-identifying content beyond counts, and
  must be reachable by Prometheus inside the compose network.
- Budget caps are hard stops that refuse work, not throttles that delay it.
- Backend gate every task: `PYTHONPATH="$PWD/shared:$PWD" pytest tests/ -q --no-cov`,
  `black --check .`, `ruff check .`, `mypy api worker shared`.
- Commit messages describe intent in plain language. No AI attribution trailers.

## Why These Six

Each corresponds to a way production breaks without anyone noticing:

| Task | Failure it prevents |
|---|---|
| 1 | A frontend-breaking change merges; 72 tests have never run on a push |
| 2 | No visibility into whether anything works |
| 3 | Ingestion returns zero articles for days while every health check stays green |
| 4 | One poison message retries forever, blocking a queue |
| 5 | A runaway ingestion loop produces a five-figure OpenAI bill |
| 6 | A known CVE ships in a dependency; `bandit` covers our code, not theirs |

---

### Task 1: Frontend CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/unit/test_ci_workflow.py` (exists; extend)

**Design notes:**

The workflow has three jobs — `lint`, `test`, `build` — all Python. The frontend has 72 tests, a
typecheck, a lint, and a production build, none of which run on a push. A frontend-breaking change
merges silently today.

`build` already depends on `[lint, test]`; add `frontend` to that list so a broken UI cannot reach
a Docker image.

Node version comes from `frontend/package.json` engines if present, else pin 20 to match the
Next.js 14 baseline. `npm ci` requires `package-lock.json` — verify it is committed before relying
on it, and fall back to `npm install` with a note if not.

- [ ] **Step 1: Extend the workflow test**

```python
def test_frontend_is_verified_in_ci() -> None:
    """72 frontend tests existed for months without ever running on a push."""
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]

    assert "frontend" in jobs
    steps = " ".join(str(step) for step in jobs["frontend"]["steps"])
    for command in ("test:run", "typecheck", "lint", "build"):
        assert command in steps


def test_docker_build_waits_for_the_frontend() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    assert "frontend" in workflow["jobs"]["build"]["needs"]
```

- [ ] **Step 2: Run to verify failure, add the job, verify green, commit**

---

### Task 2: Metrics Endpoint And Instrumentation

**Files:**
- Create: `api/metrics.py`
- Modify: `api/main.py`
- Modify: `pyproject.toml` (declare `prometheus-client`; already resolves transitively)
- Test: `tests/unit/test_metrics.py`

**Interfaces:**
- Produces: `GET /metrics`; counters `procuresignal_http_requests_total{method,path,status}`,
  `procuresignal_retrieval_articles_total{source_id,outcome}`,
  `procuresignal_enrichment_llm_calls_total{outcome}`; gauge
  `procuresignal_pipeline_last_success_timestamp{stage}`.

**Design notes:**

`prometheus.yml` has scraped `api:8000/metrics` since before this work; the endpoint has never
existed, so the scrape has always failed. That is the shape of the problem: monitoring configured,
nothing behind it.

Label on the **route template** (`/api/articles/{article_id}`), never the resolved path. Per-id
labels are unbounded cardinality and will take Prometheus down.

`pipeline_last_success_timestamp` is the one that matters. Freshness alerting in Task 3 is built on
it, and it is what catches ingestion silently returning nothing.

- [ ] **Step 1: Write failing tests**

```python
def test_metrics_endpoint_is_served(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "procuresignal_http_requests_total" in response.text


def test_paths_are_templated_not_per_id(client, auth_headers):
    """Per-id labels are unbounded cardinality and will kill the Prometheus server."""
    for article_id in range(5):
        client.get(f"/api/articles/{article_id}", headers=auth_headers)

    body = client.get("/metrics").text
    assert 'path="/api/articles/{article_id}"' in body
    assert 'path="/api/articles/3"' not in body


def test_metrics_expose_no_credentials(client, auth_headers):
    client.get("/api/feed", headers=auth_headers)
    body = client.get("/metrics").text
    assert "Bearer" not in body and "procuresignal_refresh" not in body
```

- [ ] **Step 2: Implement, verify green, commit**

---

### Task 3: Alert Rules

**Files:**
- Create: `docker/prometheus/alerts.yml`
- Modify: `prometheus.yml`, `docker-compose.yml`
- Test: `tests/unit/test_alert_rules.py`

**Design notes:**

Operational alerts for the people running the system — distinct from the customer-configured alert
rules in Phase 4. Pipeline freshness first: the classic failure is ingestion returning zero
articles for days while `/health` stays green the whole time.

Rules must reference metric names that Task 2 actually emits. A rule naming a metric nobody
publishes never fires and looks identical to a healthy system, which is the failure mode this
phase exists to remove — so the test asserts every referenced metric exists in the registry.

Minimum set: pipeline staleness per stage, retrieval error ratio, enrichment failure ratio, API 5xx
ratio, and a source stuck in `configuration_error` (which is DG FISMA's state today).

- [ ] **Step 1: Write failing tests**

```python
def test_every_alert_references_a_metric_we_publish():
    """A rule naming a metric nobody emits never fires and looks like health."""
    published = {m.name for m in REGISTRY.collect()}
    for rule in _alert_rules():
        for metric in _metrics_in(rule["expr"]):
            assert metric in published, f"{rule['alert']} watches unpublished {metric}"


def test_pipeline_staleness_is_alerted():
    assert "PipelineStale" in {rule["alert"] for rule in _alert_rules()}
```

- [ ] **Step 2: Implement, verify green, commit**

---

### Task 4: Celery Dead-Letter Queue

**Files:**
- Modify: `worker/celery_config.py`, `worker/tasks.py`
- Create: `shared/procuresignal/jobs/dead_letter.py`
- Test: `tests/unit/test_dead_letter.py`

**Design notes:**

A task exhausting its retries currently disappears into logs. The work is lost and nobody is told.

On final failure, record the task name, arguments with credentials scrubbed (reuse
`auth.audit.scrub`, do not write a second scrubber), the exception type, and the traceback, then
increment a counter Task 3 can alert on.

Arguments are scrubbed because task payloads can carry tokens. Reusing the audit scrubber keeps one
definition of what counts as sensitive.

- [ ] **Step 1: Write failing tests**

```python
def test_a_task_that_exhausts_retries_is_recorded(session):
    """Silent loss is worse than failure: nobody learns the work did not happen."""
    record_dead_letter(session, task="enrich", args={"token": "secret"}, error=ValueError("x"))
    row = dead_letters(session)[0]
    assert row.task_name == "enrich"
    assert "secret" not in str(row.payload)
    assert row.payload["token"] == "[redacted]"
```

- [ ] **Step 2: Implement, verify green, commit**

---

### Task 5: Per-Tenant LLM Budget Caps

**Files:**
- Create: `shared/procuresignal/enrichment/budget.py`
- Modify: `shared/procuresignal/enrichment/pipeline.py`
- Test: `tests/unit/test_llm_budget.py`

**Design notes:**

An in-process per-run cap already exists in `enrichment/policy.py`. It does not bound spend per
tenant and does not survive a restart, so it is not a budget — it is a batch size.

A hard stop, not a throttle: over budget means refuse the call and record why. Delaying the work
just moves the same spend later.

Enrichment is currently global rather than per tenant. Until multi-tenant enrichment exists, the
cap applies per organization where a tenant is known and to a global bucket otherwise — recorded
in the code so the seam is visible rather than implied.

- [ ] **Step 1: Write failing tests**

```python
async def test_a_tenant_over_budget_is_refused_not_delayed(session, org):
    await consume(session, organization_id=org.id, tokens=DAILY_TOKEN_BUDGET)
    assert await within_budget(session, organization_id=org.id, tokens=1) is False


async def test_one_tenant_cannot_exhaust_another(session, org, other_org):
    await consume(session, organization_id=org.id, tokens=DAILY_TOKEN_BUDGET)
    assert await within_budget(session, organization_id=other_org.id, tokens=1) is True
```

- [ ] **Step 2: Implement, verify green, commit**

---

### Task 6: Dependency Scanning

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Test: `tests/unit/test_ci_workflow.py` (extend)

**Design notes:**

`bandit` scans our code. Nothing scans our dependencies, and that is where CVEs arrive. `pip-audit`
runs against the Poetry lock. Dependabot covers pip, npm, GitHub Actions, and Docker.

`pip-audit` fails the build on a known vulnerability. If that proves too noisy in practice, the
honest response is an explicit ignore list with dates, not a non-blocking job that everyone learns
to skim past.

- [ ] **Step 1: Extend the workflow test, implement, verify green, commit, push**

---

## Self-Review

**Ordering:** Task 3 depends on Task 2's metric names. Task 4's counter is alertable once Task 3
exists but does not block it. Tasks 1, 5, 6 are independent. No task references anything defined
later.

**Deliberately out of scope:**

- **Email verification.** Needs a mail transport, which arrives with the Phase 4 notification
  engine. Splitting it here would ship half a feature.
- **Redis-backed rate limiting.** Correct and wanted, but it only matters with multiple replicas,
  which needs the hosting decision.
- **Secrets management.** A provider-neutral resolver is all that can land before hosting is
  chosen; deferring the whole item avoids building an abstraction against no concrete backend.
- **Grafana dashboards.** Phase 8, alongside SLOs and the tested restore.
- **Preference re-resolution job.** Belongs with scheduled work once the DLQ exists to catch it
  failing.
