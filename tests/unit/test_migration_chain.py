"""Structural checks on the migration chain.

These exist because the chain was broken against PostgreSQL for months while every
test passed: SQLite ignores VARCHAR length, so an over-long revision id only fails on
the database that matters.
"""

import re
from pathlib import Path

import pytest

# Alembic creates alembic_version.version_num as VARCHAR(32). A longer revision id
# applies cleanly on SQLite and fails on PostgreSQL with StringDataRightTruncation,
# part-way through the upgrade.
MAXIMUM_REVISION_LENGTH = 32

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_REVISION = re.compile(r"""^revision(?::\s*str)? = ['\"]([^'\"]+)['\"]""", re.M)
_DOWN_REVISION = re.compile(
    r"""^down_revision(?::\s*[^=]+)? = (?:['\"]([^'\"]+)['\"]|None)""", re.M
)


def _migrations() -> list[tuple[str, str | None, Path]]:
    found = []
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text()
        revision = _REVISION.search(text)
        if revision is None:
            continue
        down = _DOWN_REVISION.search(text)
        found.append((revision.group(1), down.group(1) if down else None, path))
    return found


def test_there_are_migrations_to_check() -> None:
    assert len(_migrations()) > 5


@pytest.mark.parametrize("revision,_down,path", _migrations())
def test_revision_ids_fit_the_version_column(revision: str, _down, path: Path) -> None:
    assert len(revision) <= MAXIMUM_REVISION_LENGTH, (
        f"{path.name}: revision id is {len(revision)} characters. PostgreSQL will fail "
        f"the upgrade part-way through with StringDataRightTruncation."
    )


@pytest.mark.parametrize("revision,_down,path", _migrations())
def test_filename_starts_with_its_revision_id(revision: str, _down, path: Path) -> None:
    """Alembic's own convention is <revision>_<slug>.py.

    Divergence makes a broken chain harder to trace than it needs to be, since the
    error names a revision and you have to guess which file holds it.
    """
    assert path.stem.startswith(revision)


def test_every_down_revision_exists() -> None:
    revisions = {revision for revision, _, _ in _migrations()}
    for revision, down, path in _migrations():
        if down is not None:
            assert down in revisions, f"{path.name} points at a missing revision {down!r}"


def test_the_chain_has_exactly_one_head_and_one_base() -> None:
    migrations = _migrations()
    parents = {down for _, down, _ in migrations if down}
    heads = [revision for revision, _, _ in migrations if revision not in parents]
    bases = [revision for revision, down, _ in migrations if down is None]

    assert heads == [heads[0]], f"multiple heads: {heads}"
    assert len(heads) == 1, f"multiple heads: {heads}"
    assert len(bases) == 1, f"multiple bases: {bases}"
