from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _ci_workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def test_ci_uses_the_committed_lock_for_lint_and_tests() -> None:
    workflow = _ci_workflow()

    assert workflow["env"]["POETRY_VERSION"] == "2.2.1"
    for job_name in ("lint", "test"):
        commands = "\n".join(step.get("run", "") for step in workflow["jobs"][job_name]["steps"])
        assert 'pip install "poetry==$POETRY_VERSION"' in commands
        assert "poetry install --no-interaction" in commands


def test_ci_quality_commands_are_locked_non_mutating_gates() -> None:
    workflow = _ci_workflow()
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["lint"]["steps"])

    assert "poetry run ruff check ." in commands
    assert "poetry run black . --check --diff" in commands
    assert "poetry run mypy api worker shared" in commands
    assert "--fix" not in commands
    assert "--exit-zero" not in commands
    assert "|| true" not in commands
    assert "pip install ruff black mypy" not in commands


def test_frontend_is_verified_in_ci() -> None:
    """The 72 frontend tests existed for months without ever running on a push.

    A change breaking the UI merged silently, because CI only ever checked Python.
    """
    jobs = _ci_workflow()["jobs"]

    assert "frontend" in jobs, "no frontend job: the UI is unverified on every push"

    commands = "\n".join(step.get("run", "") for step in jobs["frontend"]["steps"])
    for expected in ("npm ci", "test:run", "typecheck", "lint", "build"):
        assert expected in commands, f"frontend job never runs {expected!r}"


def test_frontend_ci_installs_from_the_committed_lock() -> None:
    """npm install would resolve fresh versions and verify something nobody is shipping."""
    commands = "\n".join(
        step.get("run", "") for step in _ci_workflow()["jobs"]["frontend"]["steps"]
    )

    assert "npm ci" in commands
    assert "npm install" not in commands


def test_docker_images_are_not_built_from_an_unverified_frontend() -> None:
    assert "frontend" in _ci_workflow()["jobs"]["build"]["needs"]


def test_dependencies_are_scanned_for_known_vulnerabilities() -> None:
    """bandit scans our code. Nothing scanned our dependencies, and that is where
    CVEs actually arrive."""
    jobs = _ci_workflow()["jobs"]

    assert "audit" in jobs
    commands = "\n".join(step.get("run", "") for step in jobs["audit"]["steps"])
    assert "pip-audit" in commands
    assert "npm audit" in commands


def test_the_audit_job_blocks_rather_than_warns() -> None:
    """A non-blocking security job is one everybody learns to skim past."""
    audit = _ci_workflow()["jobs"]["audit"]

    for step in audit["steps"]:
        assert step.get("continue-on-error") is not True


def test_dependabot_covers_every_ecosystem_we_ship() -> None:
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}

    assert {"pip", "npm", "github-actions", "docker"} <= ecosystems


def test_audit_exceptions_are_dated_decisions() -> None:
    """An ignore list without dates is just a way to make the build green.

    Every entry has to say why no upgrade closes it and when to look again.
    """
    ignore = (ROOT / ".github/pip-audit-ignore.txt").read_text()

    assert "Reviewed:" in ignore
    assert "Next review:" in ignore

    entries = [
        line.strip()
        for line in ignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert entries, "empty ignore file should be deleted rather than kept"
    assert all(entry.startswith(("PYSEC-", "GHSA-", "CVE-")) for entry in entries)


def test_the_audit_job_uses_the_ignore_list() -> None:
    commands = "\n".join(step.get("run", "") for step in _ci_workflow()["jobs"]["audit"]["steps"])

    assert "pip-audit-ignore.txt" in commands


def test_route_type_contracts_are_verified() -> None:
    """Next 16 builds with Turbopack, which emits no .next/types, so the ordinary
    build never checks a page's props against its generated route contract.

    A dynamic route declaring synchronous params passed CI and failed under webpack.
    """
    commands = "\n".join(
        step.get("run", "") for step in _ci_workflow()["jobs"]["frontend"]["steps"]
    )

    assert "verify:routes" in commands
