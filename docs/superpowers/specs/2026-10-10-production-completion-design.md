# ProcureSignal Production Completion Design

**Date:** 2026-10-10  
**Status:** Approved in conversation; pending written-spec review  
**Canonical roadmap:** `docs/superpowers/plans/2026-08-01-production-readiness-roadmap.md`

## 1. Purpose

Finish every production-readiness task that can be completed without choosing a hosting vendor,
supplying third-party credentials, or making legal decisions on the owner's behalf. The finished
repository must provide one honest verification path that proves the application, database,
workers, frontend, operational controls, and critical user journeys work together.

This program completes canonical Phases 7, 8, and 9. It does not reopen completed product phases
unless verification exposes a defect in them.

## 2. Success Criteria

The engineering program is complete when all of the following are true:

1. The GDPR processing record and personal-data inventory are generated from the code registry,
   and CI fails when either document is stale.
2. A PostgreSQL backup can be created, validated, restored into an isolated database, migrated to
   the current schema, and exercised by an application-level readiness check.
3. Prometheus and Grafana expose actionable service, pipeline, worker, notification, and LLM-cost
   signals with documented service-level objectives.
4. One repository command dynamically discovers and executes every required backend, database,
   Redis, frontend, migration, audit, container, and end-to-end verification gate.
5. A browser-level critical-path test covers the main authenticated procurement workflow.
6. Dead, duplicate, stale, hardcoded, and misleading code or documentation is removed only when
   references, packaging, tests, and tooling prove it is unused.
7. The README, operational documentation, demo instructions, and canonical tracker describe what
   the repository actually does.
8. Every implementation task has fresh test evidence, a focused human-readable commit, and a
   successful hosted CI run before it is considered complete.

## 3. Non-Goals And External Boundaries

Engineering cannot honestly complete these items without external input:

- Selecting AWS, Azure, GCP, or another production host.
- Proving cloud-region data residency, cloud backups, or provider-specific disaster recovery.
- Sending real email without SMTP or transactional-email credentials.
- Granting content redistribution rights or choosing a commercial news-data contract.
- Approving GDPR lawful-basis wording or the Article 17(3) audit-retention position.
- Adding Slack or Teams delivery without workspace credentials.

The repository will contain portable interfaces, local proofs, runbooks, and explicit owner-input
markers for these items. It will not contain fake credentials, speculative vendor configuration,
or claims that an external integration has been verified when it has not.

## 4. Delivery Architecture

### 4.1 Phase 7: generated privacy records

`shared/procuresignal/privacy/inventory.py` remains the single source of truth for personal-data
handling. A deterministic generator will render both the personal-data inventory and Article 30
processing record. A `--check` mode will compare generated output with committed documents without
rewriting them and will return a non-zero exit status on drift. Unit tests and CI will exercise the
same public generator interface.

Legal assertions that code cannot determine will be rendered as visible `OWNER INPUT REQUIRED`
entries. Generated sections must be reproducible regardless of machine, locale, or current time.

### 4.2 Phase 8: portable recovery and observability

Backup and restore will be implemented as provider-neutral scripts around PostgreSQL's supported
logical backup tools. Configuration will come from explicit environment variables or existing
application settings; credentials will never be embedded in commands, source files, or logs.

The restore drill will use an isolated database so it cannot overwrite the active development or
production database. It will:

1. create or accept a backup artifact;
2. verify that the artifact is non-empty and readable;
3. restore it into a newly created isolated database;
4. run the complete Alembic migration chain to the current head;
5. perform schema and application-readiness assertions; and
6. remove drill resources unless preservation is explicitly requested for diagnosis.

Prometheus rules and Grafana dashboards will cover API availability and latency, worker and queue
health, pipeline freshness, retrieval failures, sanctions-screening freshness, notification
delivery, and LLM-budget pressure. The runbook will define initial SLOs, their calculation, alert
ownership, and the conditions under which thresholds should be revised.

### 4.3 Phase 9: one verification contract

`scripts/verify.sh` will be the public verification entry point. It will use strict shell behavior,
resolve paths relative to the repository root, detect required tools, print actionable failures,
and avoid silently skipping a gate. Optional external-service gates must be explicitly selected;
when a required mode is selected, missing dependencies are failures rather than skips.

Verification will be layered so developers can run useful subsets while CI and release mode run
the complete contract. The complete contract covers:

- backend unit and integration tests with coverage;
- real PostgreSQL tests and a clean migration chain;
- shared Redis behavior;
- formatting, linting, type checking, dependency and source security audits;
- search evaluation floors;
- frontend unit tests, type checking, linting, production build, and route contracts;
- Docker image builds and process-start checks;
- backup/restore drill;
- API/WebSocket smoke tests; and
- browser-level critical-path tests.

The script must invoke project-owned test commands and discover tests through the relevant test
runners. It must not maintain a brittle hand-written list of individual test files or suppress
failures to manufacture a green result.

### 4.4 Browser critical path

The browser test will exercise behavior rather than styling. Against an isolated Compose stack it
will create a tenant and user, authenticate, restore the session, open the feed, perform a search,
create or inspect a supplier watchlist, view notifications, start an agent analysis, and verify the
human approval boundary. Test data will be deterministic and will not require paid APIs.

External news and LLM calls will remain behind the existing deterministic test boundaries. A
failure must identify the user-visible step that failed and retain diagnostics suitable for CI.

### 4.5 Final engineering sweep

Cleanup follows evidence, not file age or naming. A candidate is removable only after checking:

- source references and dynamic imports;
- package manifests and build inputs;
- Dockerfiles and Compose configuration;
- CI workflows and scripts;
- migrations and operational runbooks; and
- test fixtures and test discovery.

Duplicate behavior will be consolidated behind the existing domain boundary that owns it. Large
folder moves are permitted only when they reduce a demonstrated dependency or packaging problem;
an aesthetic repository-wide rearrangement is out of scope because it creates risk without adding
production capability.

Hardcoded values are classified before removal. Security ceilings and protocol invariants remain
constants with rationale; environment-dependent endpoints, credentials, schedules, thresholds,
and retention choices move to validated settings only when operators genuinely need to change
them. Defaults must be safe and documented.

## 5. Error Handling And Safety

- Privacy document generation fails closed on unregistered or unsupported inventory entries.
- Backup commands never print passwords and never overwrite an existing artifact unless explicitly
  requested.
- Restore refuses the configured primary application database and requires an isolated target.
- Destructive drill cleanup is limited to resources created by that drill.
- Verification stops on the first unsafe precondition and returns the failing command's status.
- No end-to-end test calls paid or live data providers.
- CI artifacts retain browser traces, logs, and restore diagnostics only when useful and must not
  contain secrets or personal data.

## 6. Testing Strategy

Every behavior change uses red-green-refactor:

1. add the smallest test that expresses the missing behavior;
2. run it and confirm it fails for the intended reason;
3. implement the minimum production change;
4. run the focused test and then the complete relevant suite; and
5. refactor only while all tests remain green.

Shell and CI behavior will have contract tests that inspect observable exit codes and output rather
than merely searching source text. PostgreSQL-specific behavior will run against pgvector-enabled
PostgreSQL with `REQUIRE_POSTGRES=1`. Browser tests will use deterministic fixtures and capture a
trace on failure.

Before each push, the task's focused tests and all applicable repository gates must pass locally.
After each push, the GitHub Actions run for that exact commit must complete successfully. A local
pass and a hosted pass are reported separately.

## 7. Commit And Release Discipline

Work lands as small, dependency-ordered commits on `main`, matching the owner's requested delivery
model. Commit subjects describe the operational intent in natural language and contain no AI
attribution. The order is:

1. finish generated privacy records;
2. add portable backup and tested restore;
3. add SLOs, alert rules, and dashboards;
4. establish the unified verification contract;
5. add browser critical-path verification;
6. perform the evidence-based cleanup and documentation pass; and
7. run and record final local and hosted verification.

If a task exposes a defect in an already completed phase, the defect is fixed with its own failing
regression test and focused commit before continuing.

## 8. Completion Report

The final report will include:

- commits and delivered capabilities;
- exact local verification commands and results;
- the GitHub Actions result for the final commit;
- backup and restore evidence;
- browser critical-path evidence;
- removed code and the proof used to classify it as unused;
- remaining external owner actions; and
- an explicit verdict for engineering completion, demo readiness, and production launch readiness.

“Engineering complete” will not be used until every buildable item above has fresh evidence.
“Production launch ready” will remain false while any required legal, licensing, credential, or
hosting decision is outstanding.
