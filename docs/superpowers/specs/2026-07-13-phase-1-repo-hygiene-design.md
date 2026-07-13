# Phase 1: Repository Hygiene Design

## Objective

Clean ProcureSignal's repository without changing product behavior. Remove generated artifacts, duplicate and stale files, and production code proven unused. Preserve unique valid logic, strengthen repository safeguards, and leave `main` fully validated and ready for Phase 2.

## Scope

Phase 1 includes:

- Removing local numbered coverage databases and stale Next.js build output.
- Comparing every duplicate-suffixed source and test file with its canonical file.
- Preserving unique, current logic from a duplicate when the canonical file does not contain it.
- Deleting duplicate, repeated, obsolete, and conclusively dead code.
- Organizing tests only where necessary to remove duplication or obsolete coverage.
- Extending ignore rules to prevent known generated artifacts from recurring.
- Running the complete backend and frontend validation suite.

Phase 1 excludes:

- Product features, API behavior changes, UI redesign, and database migrations.
- Phase 2 cost optimization or changes to LLM behavior.
- Broad architectural substitutions such as Kafka, Kubernetes, a vector database, or a data warehouse.
- Committing `docs/interview-preparation.md`; it remains preserved locally and will be updated in Phase 10 after the product implementation is accurate.

## Cleanup Workflow

1. Record the pre-cleanup worktree and validation baseline.
2. Inventory generated, untracked, duplicate-suffixed, stale, and potentially dead files.
3. Compare each differing duplicate with its canonical counterpart and relevant Git history.
4. Merge unique valid logic into the canonical file only when it is current, required, and missing.
5. Delete generated artifacts, redundant duplicates, and stale files.
6. Audit production code for unused modules, functions, imports, routes, jobs, components, and configuration.
7. Remove a candidate only when references, framework wiring, tooling, and tests establish that it is unused.
8. Update ignore rules for recurring artifact patterns.
9. Run all validation gates and investigate any regression.
10. Review the final diff to confirm that changes are limited to repository hygiene.

## Dead-Code Evidence Standard

Production code may be removed only when all relevant checks support removal:

- Static reference searches find no consumers.
- The code is not registered through FastAPI routers, Celery tasks, APScheduler jobs, Next.js conventions, React composition, configuration, or another framework mechanism.
- It is not loaded dynamically through imports, names, environment configuration, scripts, Docker, or CI.
- Tests do not demonstrate a supported behavior that depends on it.
- Git history and duplicate comparison do not show that it contains a newer fix missing from the canonical implementation.

Uncertain candidates remain in place and are recorded with the reason that removal could not be proven safe. Tests must not be weakened or deleted merely to make a removal pass.

## Duplicate Resolution

Identical duplicate-suffixed files are deleted. Differing duplicates are reviewed line by line against their canonical files and recent history. Unique content is classified as one of:

- Already superseded or obsolete: delete with the duplicate.
- Valid but already represented differently: retain the canonical implementation.
- Valid, current, and missing: integrate the smallest necessary change into the canonical file, validate it, then delete the duplicate.

This process applies equally to source files and tests so unique regression coverage is not lost.

## Validation And Failure Handling

The pre-cleanup baseline distinguishes existing failures from cleanup regressions. The final validation includes, where configured by the repository:

- Black formatting checks.
- Ruff lint checks.
- MyPy type checking.
- Full Pytest backend test suite.
- ESLint checks.
- TypeScript type checking.
- Full Vitest frontend test suite.
- Next.js production build.
- Review of Docker and CI configuration alignment.

If cleanup causes a failure, stop and identify the dependency or behavior that was incorrectly classified. Restore the required behavior or revise the cleanup; do not suppress the failure, loosen validation, or remove the protecting test.

## Repository Safeguards

Ignore rules will cover the observed recurrence patterns, including numbered coverage files and stale Next.js build directories, while remaining narrow enough not to hide legitimate source files. The final worktree should contain no duplicate-suffixed source/test files or generated build artifacts. The intentionally deferred interview document is the only known local artifact preserved outside the Phase 1 commit.

## Quality Principles From The Product Roadmap

Later phases will use the interview document as an architecture and quality checklist. Decisions will favor explainability, deterministic processing before LLM use, cost control, isolated pipeline stages, human approval for consequential procurement actions, measurable accuracy, and production-grade operations. Technologies listed as alternatives are not automatically improvements; they will be adopted only when requirements and evidence justify their complexity.

## Success Criteria

Phase 1 is complete when:

- Generated coverage and stale build artifacts are removed.
- No duplicate-suffixed source or test files remain.
- Unique valid logic and regression coverage from differing duplicates are preserved in canonical files.
- All conclusively dead production code found in the scoped audit is removed.
- Ignore rules prevent the observed artifacts from recurring.
- No intended product behavior, API contract, schema, or UI flow changes.
- All configured backend and frontend validation gates pass.
- The final diff is focused, reviewable, and leaves `main` ready for a separately designed Phase 2.
