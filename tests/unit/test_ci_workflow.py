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
