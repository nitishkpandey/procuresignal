"""The worker image must contain everything worker code imports.

`worker/tasks.py` imported `api.metrics` while Dockerfile.worker copies only `shared`
and `worker`. Every test passed, because tests import from the source tree where `api`
is present, and the real container could not start.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _copied_paths(dockerfile: Path) -> set[str]:
    """Top-level source directories a Dockerfile copies into the image."""
    copied = set()
    for line in dockerfile.read_text().splitlines():
        match = re.match(r"^COPY\s+\./?([A-Za-z_][A-Za-z0-9_]*)\s", line.strip())
        if match:
            copied.add(match.group(1))
    return copied


def _first_party_imports(package: Path) -> set[str]:
    """Top-level first-party packages imported anywhere under `package`."""
    local = {p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")}
    found: set[str] = set()

    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in local:
                        found.add(root)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root in local:
                    found.add(root)
    return found


@pytest.mark.parametrize(
    ("dockerfile", "package"),
    [("Dockerfile.worker", "worker"), ("Dockerfile.api", "api")],
)
def test_the_image_contains_everything_its_code_imports(dockerfile: str, package: str) -> None:
    copied = _copied_paths(ROOT / dockerfile)
    imported = _first_party_imports(ROOT / package)

    # `procuresignal` lives inside shared/, which is copied under that name.
    imported.discard("procuresignal")
    missing = imported - copied - {package}

    assert not missing, (
        f"{dockerfile} does not copy {sorted(missing)}, which {package}/ imports. "
        f"The container will fail to start, and no test will notice because tests "
        f"import from the source tree."
    )


def test_the_worker_does_not_depend_on_the_api_package() -> None:
    """A layering rule, not just a packaging one: the worker runs without an API."""
    assert "api" not in _first_party_imports(ROOT / "worker")
