# Phase 8 Recovery And Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that ProcureSignal data can be restored and that operators can see and act on violations of the system's reliability objectives.

**Architecture:** A provider-neutral Python recovery module wraps PostgreSQL's supported client tools without exposing credentials and restores only into generated isolated databases. Prometheus recording rules turn existing metrics plus notification outcomes into SLI series, alert rules enforce initial objectives, and provisioned Grafana dashboards make the same series visible under Docker Compose.

**Tech Stack:** Python 3.11, PostgreSQL 15 client tools, SQLAlchemy, Alembic, pytest, Prometheus, Grafana, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-10-production-completion-design.md`

## Global Constraints

- A restore drill never writes to the source database and accepts only a generated `procuresignal_restore_<12-hex-character>` target name.
- Passwords travel through `PGPASSWORD`, never command arguments, logs, exceptions, or generated reports.
- Backup output is written atomically and an existing artifact is not overwritten without an explicit flag.
- A successful drill proves archive readability, restore, current Alembic head, and every SQLAlchemy-declared table.
- SLOs are initial operational contracts with documented revision rules, not claims about production history.
- Cloud storage, region replication, provider monitoring, and production scheduling remain deferred until hosting is selected.
- All Docker images and dashboard references use pinned major versions or immutable repository files; no hidden manual dashboard setup.

## Review Focus

- A database URL with reserved characters in its password must not leak or be incorrectly shell-quoted.
- A failed restore or readiness check must still remove the drill database unless `--keep-failed` was explicitly passed.
- An archive path that already exists must be rejected before `pg_dump` starts.
- Prometheus rules must distinguish “no traffic” from “all requests succeeded” and avoid divide-by-zero alerts.
- Grafana must start with the datasource and dashboard already provisioned on an empty volume.

---

### Task 1: Safe logical backup and real restore drill

**Files:**
- Create: `shared/procuresignal/operations/__init__.py`
- Create: `shared/procuresignal/operations/recovery.py`
- Create: `scripts/database_recovery.py`
- Create: `tests/unit/test_database_recovery.py`
- Create: `tests/postgres/test_database_recovery_pg.py`
- Create: `docs/operations/backup-and-restore.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `PostgresEndpoint.from_url(url: str) -> PostgresEndpoint`.
- Produces: `PostgresEndpoint.tool_args(database: str | None = None) -> list[str]`.
- Produces: `PostgresEndpoint.environment(base: Mapping[str, str] | None = None) -> dict[str, str]`.
- Produces: `create_backup(url: str, output: Path, *, overwrite: bool = False) -> Path`.
- Produces: `async restore_drill(url: str, archive: Path, *, keep_failed: bool = False) -> RestoreReceipt`.
- Produces CLI: `python scripts/database_recovery.py backup --database-url URL --output PATH [--overwrite]`.
- Produces CLI: `python scripts/database_recovery.py drill --database-url URL --archive PATH [--keep-failed]`.

- [ ] **Step 1: Write failing unit tests for command and safety contracts**

Create `tests/unit/test_database_recovery.py` containing:

```python
import os
from pathlib import Path

import pytest
from procuresignal.operations.recovery import (
    PostgresEndpoint,
    backup_command,
    restore_command,
    validate_drill_database,
)


URL = "postgresql+asyncpg://buyer:p%40ss@db.example:5544/procuresignal"


def test_password_is_only_in_the_child_environment() -> None:
    endpoint = PostgresEndpoint.from_url(URL)
    command = backup_command(endpoint, Path("backup.dump"))
    assert "p@ss" not in " ".join(command)
    assert endpoint.environment({"PATH": os.environ.get("PATH", "")})["PGPASSWORD"] == "p@ss"


def test_backup_command_is_custom_format_without_ownership(tmp_path: Path) -> None:
    command = backup_command(PostgresEndpoint.from_url(URL), tmp_path / "backup.dump.tmp")
    assert command[0] == "pg_dump"
    assert "--format=custom" in command
    assert "--no-owner" in command
    assert "--no-privileges" in command


def test_restore_command_refuses_the_source_database(tmp_path: Path) -> None:
    endpoint = PostgresEndpoint.from_url(URL)
    with pytest.raises(ValueError, match="source database"):
        restore_command(endpoint, tmp_path / "backup.dump", "procuresignal")


@pytest.mark.parametrize("name", ["postgres", "procuresignal", "restore_test", "x;drop database"])
def test_only_generated_drill_names_are_accepted(name: str) -> None:
    with pytest.raises(ValueError, match="procuresignal_restore_"):
        validate_drill_database(name, source_database="procuresignal")
```

- [ ] **Step 2: Run unit tests and verify RED**

Run:

```bash
poetry run pytest tests/unit/test_database_recovery.py -v --no-cov
```

Expected: collection fails because `procuresignal.operations.recovery` does not exist.

- [ ] **Step 3: Implement URL parsing, command construction, and atomic backup**

Implement `PostgresEndpoint` as a frozen dataclass built with `sqlalchemy.engine.make_url`. Accept only `postgresql` and `postgresql+asyncpg`; require host, username, and database. `tool_args()` returns separate `--host`, `--port`, `--username`, and `--dbname` arguments. `environment()` copies the supplied environment and adds `PGPASSWORD` only when a password exists.

Implement these exact command shapes:

```python
def backup_command(endpoint: PostgresEndpoint, temporary_output: Path) -> list[str]:
    return [
        "pg_dump",
        *endpoint.tool_args(),
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-privileges",
        f"--file={temporary_output}",
    ]


def restore_command(endpoint: PostgresEndpoint, archive: Path, database: str) -> list[str]:
    validate_drill_database(database, source_database=endpoint.database)
    return [
        "pg_restore",
        *endpoint.tool_args(database),
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        str(archive),
    ]
```

`create_backup()` checks executables with `shutil.which`, refuses an existing output unless `overwrite=True`, writes to `output.with_suffix(output.suffix + ".tmp")`, runs `subprocess.run(command, check=True, env=endpoint.environment())`, rejects an empty temporary file, and atomically replaces the output with `Path.replace()`. It removes the temporary file on every failure.

- [ ] **Step 4: Verify unit tests GREEN and add failure-path tests**

Add tests using a temporary executable placed first on `PATH` to prove:

- an existing output is unchanged when overwrite is false;
- a child failure leaves no temporary or final artifact;
- an empty successful child output is rejected; and
- exception text contains neither raw nor percent-encoded password.

Run:

```bash
poetry run pytest tests/unit/test_database_recovery.py -v --no-cov
```

Expected: all unit tests pass.

- [ ] **Step 5: Write the failing PostgreSQL restore test**

Create `tests/postgres/test_database_recovery_pg.py` with `pytest.mark.postgres`. The test must:

1. obtain `TEST_DATABASE_URL` and fail when `REQUIRE_POSTGRES=1` but it is absent;
2. run the complete Alembic chain against a generated source database;
3. insert an organization row with slug `restore-proof`;
4. call `create_backup()` into `tmp_path`;
5. call `restore_drill()`; and
6. assert the receipt reports the current Alembic head, includes every name in `Base.metadata.tables`, and confirms `restore-proof` survived.

Name the test `test_backup_restores_current_schema_and_application_data` so CI output states the guarantee being proved.

- [ ] **Step 6: Run the PostgreSQL test and verify RED**

Run:

```bash
REQUIRE_POSTGRES=1 \
TEST_DATABASE_URL=postgresql+asyncpg://procuresignal:procuresignal@localhost:5432/postgres \
poetry run pytest tests/postgres/test_database_recovery_pg.py -v --no-cov
```

Expected: failure because `restore_drill()` is not implemented.

- [ ] **Step 7: Implement isolated restore and readiness verification**

`restore_drill()` generates `procuresignal_restore_<12 lowercase hex characters>`. It uses `createdb` with the maintenance database from the supplied URL, restores with `pg_restore`, runs `alembic upgrade head` under an environment whose `DATABASE_URL` is the generated target URL, and queries the restored database with SQLAlchemy async to verify:

- `alembic_version.version_num` equals the single result of `ScriptDirectory.from_config(config).get_current_head()`;
- every table in `Base.metadata.tables` exists; and
- a simple `SELECT 1` succeeds.

Return a frozen `RestoreReceipt(database, alembic_head, tables, proof_rows)` where `proof_rows` counts organizations whose slug is `restore-proof`. In `finally`, invoke `dropdb --if-exists --force` unless `keep_failed=True` and an exception occurred. Never include the full URL in logs or the receipt.

The CLI reads `DATABASE_URL` when `--database-url` is omitted, prints only artifact path or receipt fields, and exits non-zero on any subprocess or readiness failure.

- [ ] **Step 8: Verify the real restore drill GREEN**

Run the command from Step 6 again. Expected: pass, with no `procuresignal_restore_%` database left behind. Confirm cleanup with:

```bash
psql postgresql://procuresignal:procuresignal@localhost:5432/postgres \
  -Atc "select datname from pg_database where datname like 'procuresignal_restore_%'"
```

Expected: no output.

- [ ] **Step 9: Add CI and operator documentation**

In the test job, install `postgresql-client`, then add a separate step:

```yaml
      - name: Prove a backup can be restored
        run: poetry run pytest tests/postgres/test_database_recovery_pg.py -v --no-cov
        env:
          TEST_DATABASE_URL: postgresql+asyncpg://procuresignal:procuresignal@localhost:5432/postgres
          REQUIRE_POSTGRES: '1'
```

Document backup, overwrite protection, drill, failure preservation, cleanup, credential handling, scheduling expectations, encryption/storage responsibilities, RPO/RTO measurement, and the fact that off-host storage waits on the hosting decision in `docs/operations/backup-and-restore.md`.

- [ ] **Step 10: Run gates, commit, push, and confirm hosted CI**

Run backend and PostgreSQL gates from the canonical roadmap, then:

```bash
git add shared/procuresignal/operations scripts/database_recovery.py \
  tests/unit/test_database_recovery.py tests/postgres/test_database_recovery_pg.py \
  docs/operations/backup-and-restore.md .github/workflows/ci.yml
git commit -m "Prove that a database backup can be restored"
git push origin main
```

Wait for the exact commit's CI run to succeed before Task 2.

---

### Task 2: Service-level indicators, objectives, and alerts

**Files:**
- Modify: `shared/procuresignal/observability/metrics.py`
- Modify: `shared/procuresignal/notifications/transports/in_app.py`
- Create: `docker/prometheus/slo-rules.yml`
- Modify: `docker/prometheus/alerts.yml`
- Modify: `prometheus.yml`
- Modify: `docker-compose.yml`
- Create: `docs/operations/service-level-objectives.md`
- Modify: `tests/unit/test_metrics.py`
- Modify: `tests/unit/test_alert_rules.py`
- Create: `tests/unit/test_slo_rules.py`

**Interfaces:**
- Produces metric `procuresignal_notification_deliveries_total{transport,outcome}`.
- Produces `record_notification_delivery(transport: str, outcome: str) -> None`.
- Produces recording rules `procuresignal:api_availability:ratio_5m`, `procuresignal:api_latency_p95_seconds:5m`, and `procuresignal:notification_delivery_success:ratio_30m`.

- [ ] **Step 1: Write failing metric and SLO contract tests**

Add a metric test that delivers once with `InAppTransport` and once with a transport that raises, then asserts counter deltas for `outcome="success"` and `outcome="failed"`.

Create `tests/unit/test_slo_rules.py` that parses `docker/prometheus/slo-rules.yml` and asserts exactly these record names:

```python
EXPECTED_RECORDS = {
    "procuresignal:api_availability:ratio_5m",
    "procuresignal:api_latency_p95_seconds:5m",
    "procuresignal:notification_delivery_success:ratio_30m",
}
```

The test also asserts each expression uses a non-zero denominator guard, `prometheus.yml` loads the file, and Compose mounts it.

Extend alert tests to require `ApiTargetDown`, `WorkerTargetDown`, `ApiAvailabilitySloBurn`, `ApiLatencySloBurn`, and `NotificationDeliverySloBurn`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
poetry run pytest tests/unit/test_metrics.py tests/unit/test_alert_rules.py \
  tests/unit/test_slo_rules.py -v --no-cov
```

Expected: failures for the missing metric, recording-rule file, mount, and alerts.

- [ ] **Step 3: Add and instrument delivery outcome metric**

In `metrics.py`, declare:

```python
NOTIFICATION_DELIVERIES = Counter(
    f"{NAMESPACE}_notification_deliveries_total",
    "Notification delivery attempts, by transport and outcome.",
    ["transport", "outcome"],
)


def record_notification_delivery(transport: str, outcome: str) -> None:
    NOTIFICATION_DELIVERIES.labels(transport=transport, outcome=outcome).inc()
```

In `deliver_pending()`, record `failed` inside the exception branch and `success` immediately after `mark_delivered()`. Use `transport.name` and do not record queued rows that were never attempted.

- [ ] **Step 4: Add recording and alert rules**

Create `slo-rules.yml` with one group named `procuresignal-sli`. Use these expressions:

```promql
1 - (
  sum(rate(procuresignal_http_requests_total{status=~"5.."}[5m]))
  / clamp_min(sum(rate(procuresignal_http_requests_total[5m])), 0.001)
)
```

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(procuresignal_http_request_seconds_bucket[5m]))
)
```

```promql
sum(rate(procuresignal_notification_deliveries_total{outcome="success"}[30m]))
/
clamp_min(sum(rate(procuresignal_notification_deliveries_total[30m])), 0.001)
```

Mount and load the file beside `alerts.yml`. Add target-down alerts using `up{job="procuresignal-api"} == 0` and `up{job="procuresignal-worker"} == 0`, plus SLO-burn alerts with initial objectives: API availability at least 99.5%, API p95 below 500 ms, and notification success at least 99%. Every alert has a non-empty `for`, `severity`, summary, and actionable description. Gate ratio alerts with positive request/attempt rates so an idle system does not page.

- [ ] **Step 5: Document objective ownership and measurement**

`docs/operations/service-level-objectives.md` must define the three objectives, measurement windows, exclusions, alert response, review cadence, and the trigger for changing a threshold. State that these are initial objectives to be validated with production traffic, not historical achievements.

- [ ] **Step 6: Run focused and complete backend gates**

Run Step 2's command, then the complete backend gate. Additionally validate Prometheus syntax with:

```bash
docker run --rm \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/docker/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v3.7.3 \
  promtool check config /etc/prometheus/prometheus.yml
```

Expected: all tests and `promtool` checks pass.

- [ ] **Step 7: Commit, push, and confirm hosted CI**

```bash
git add shared/procuresignal/observability/metrics.py \
  shared/procuresignal/notifications/transports/in_app.py \
  docker/prometheus/slo-rules.yml docker/prometheus/alerts.yml \
  prometheus.yml docker-compose.yml docs/operations/service-level-objectives.md \
  tests/unit/test_metrics.py tests/unit/test_alert_rules.py tests/unit/test_slo_rules.py
git commit -m "Turn operating signals into reliability objectives"
git push origin main
```

Wait for the exact commit's CI run to succeed before Task 3.

---

### Task 3: Provisioned operations dashboard

**Files:**
- Create: `docker/grafana/provisioning/datasources/prometheus.yml`
- Create: `docker/grafana/provisioning/dashboards/procuresignal.yml`
- Create: `docker/grafana/dashboards/procuresignal-operations.json`
- Modify: `docker-compose.yml`
- Create: `tests/unit/test_grafana_provisioning.py`
- Modify: `docs/operations/service-level-objectives.md`

**Interfaces:**
- Produces Grafana datasource UID `procuresignal-prometheus`.
- Produces dashboard UID `procuresignal-operations`.
- Produces dashboard panels for target health, API availability, API p95, pipeline age, retrieval failures, dead letters, notification success/backlog, sanctions coverage, embedding backlog, and LLM-budget refusals.

- [ ] **Step 1: Write failing provisioning tests**

Create `tests/unit/test_grafana_provisioning.py` to parse YAML/JSON and assert:

- the datasource URL is `http://prometheus:9090` and is default;
- the provider reads `/var/lib/grafana/dashboards` without UI write-back;
- dashboard UID/title exist and panel IDs are unique;
- every required panel title exists;
- every Prometheus target uses datasource UID `procuresignal-prometheus`;
- the dashboard contains each Phase 8 recording rule and the raw freshness/backlog/cost metrics; and
- Compose mounts both provisioning and dashboards read-only.

- [ ] **Step 2: Run the test and verify RED**

```bash
poetry run pytest tests/unit/test_grafana_provisioning.py -v --no-cov
```

Expected: fail because no provisioning files exist.

- [ ] **Step 3: Create provisioning and dashboard files**

Provision a Prometheus datasource with UID `procuresignal-prometheus`. Provision dashboards from `/var/lib/grafana/dashboards` with `allowUiUpdates: false`.

Create one dashboard with refresh `30s`, default range `now-6h`, and these panel expressions:

- target health: `up{job=~"procuresignal-api|procuresignal-worker"}`;
- availability: `procuresignal:api_availability:ratio_5m`;
- API p95: `procuresignal:api_latency_p95_seconds:5m`;
- pipeline age: `time() - procuresignal_pipeline_last_success_timestamp`;
- retrieval failures: `sum by (source_id) (increase(procuresignal_retrieval_articles_total{outcome!="success"}[8h]))`;
- dead letters: `sum by (task) (increase(procuresignal_dead_letters_total[1h]))`;
- notification success: `procuresignal:notification_delivery_success:ratio_30m`;
- notification backlog: `procuresignal_notifications_pending`;
- sanctions unmatched ratio: the same guarded 24-hour ratio as the alert;
- embedding backlog: `procuresignal_embeddings_pending`;
- budget refusals: `sum by (tenant) (increase(procuresignal_llm_budget_refusals_total[1h]))`.

Use stat panels for target health and current backlogs, time-series panels for ratios/latency/age, percent units for ratios, seconds for latency/age, and thresholds matching the SLO document.

- [ ] **Step 4: Mount provisioning and prove Grafana loads it**

Add read-only mounts:

```yaml
      - ./docker/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro
```

Run the focused test, then:

```bash
AUTH_SECRET_KEY=local-verification-secret docker compose up -d prometheus grafana
curl --fail http://localhost:3001/api/health
curl --fail --user admin:admin \
  http://localhost:3001/api/dashboards/uid/procuresignal-operations
AUTH_SECRET_KEY=local-verification-secret docker compose down
```

Expected: health reports a database status of `ok`, and the dashboard endpoint returns UID `procuresignal-operations`.

- [ ] **Step 5: Run gates, commit, push, and confirm hosted CI**

Run the complete backend gate and `docker compose config --quiet`, then:

```bash
git add docker/grafana docker-compose.yml tests/unit/test_grafana_provisioning.py \
  docs/operations/service-level-objectives.md
git commit -m "Provision the dashboard operators need on first boot"
git push origin main
```

Wait for the exact commit's CI run to succeed. Phase 8's provider-neutral scope is complete only after the restore drill and fresh-volume dashboard checks have both passed.

## Self-Review

- **Spec coverage:** Task 1 proves backup/restore and documents provider boundaries; Task 2 defines measurable SLOs and alerts; Task 3 provisions dashboards.
- **Type consistency:** The backup CLI consumes the same `PostgresEndpoint`, `create_backup`, and `restore_drill` interfaces tested in unit/PostgreSQL tests. Dashboard expressions use Task 2's exact record names.
- **Review-focus coverage:** reserved-password handling, cleanup on failure, overwrite refusal, idle Prometheus ratios, and empty-volume Grafana provisioning each have an explicit automated or runtime proof.
- **Scope:** No cloud vendor, production schedule, storage bucket, or data-residency claim is introduced.
