"""Migrations must be safe to apply while the previous version is still serving.

A destructive change in the same deploy as the code that stops using it means the old
pods hit a column that is already gone. The fix is expand/contract: add in one release,
stop using it, remove in a later one. That was written in the roadmap and enforced
nowhere, so this is the enforcement.
"""

import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"

# Operations that break a running previous version the moment they land.
DESTRUCTIVE = {
    "drop_column": "removes a column the running release may still select",
    "drop_table": "removes a table the running release may still query",
    "drop_constraint": "can break writes the running release still makes",
    "alter_column": "a type or nullability change can reject the running release's writes",
}

# Revisions predating this rule. Fixed list: it must not grow silently, so a new
# migration cannot be excused by adding itself here without the diff being obvious.
GRANDFATHERED = {
    "9739a6693138",
    "1f8f95ad327b",
    "1a2b3c_add_signals_tables",
    "a1b2c3_add_chat_tables",
    "b2c3d4_signals_impact_areas_json",
    "c3d4e5_add_platform_language",
    "d4e5f6_add_risk_events",
    "e5f6a7_risk_scan_tracking",
    "f6a7b8_enrichment_cache",
    "f7b8c9_terminal_enrichment",
    "f8c9d0_retrieval_audit",
}

_REVISION = re.compile(r"""^revision(?::\s*str)? = ['"]([^'"]+)['"]""", re.M)
_ACKNOWLEDGED = "expand/contract"


def _migrations() -> list[tuple[str, str, Path]]:
    found = []
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text()
        match = _REVISION.search(text)
        if match:
            found.append((match.group(1), text, path))
    return found


def _upgrade_body(text: str) -> str:
    start = text.find("def upgrade()")
    if start == -1:
        return ""
    end = text.find("def downgrade()", start)
    return text[start : end if end != -1 else len(text)]


@pytest.mark.parametrize("revision,text,path", _migrations())
def test_upgrades_are_safe_against_the_running_release(
    revision: str, text: str, path: Path
) -> None:
    """A destructive upgrade must say, in the file, why it is safe to deploy."""
    if revision in GRANDFATHERED:
        pytest.skip("predates this rule")

    body = _upgrade_body(text)
    for operation, why in DESTRUCTIVE.items():
        if f"op.{operation}(" in body and _ACKNOWLEDGED not in text:
            pytest.fail(
                f"{path.name} calls op.{operation} in upgrade(), which {why}. "
                f"Either split it into expand and contract releases, or document why "
                f"this one is safe using the phrase {_ACKNOWLEDGED!r}."
            )


def test_the_grandfathered_list_does_not_grow() -> None:
    """An exception list that grows is a rule nobody follows."""
    revisions = {revision for revision, _, _ in _migrations()}

    assert GRANDFATHERED <= revisions, "grandfathered revision no longer exists"
    assert len(GRANDFATHERED) == 11


@pytest.mark.parametrize("revision,text,path", _migrations())
def test_every_migration_has_a_downgrade(revision: str, text: str, path: Path) -> None:
    """A migration that cannot be reversed turns a bad deploy into a restore."""
    assert "def downgrade()" in text, f"{path.name} has no downgrade"
