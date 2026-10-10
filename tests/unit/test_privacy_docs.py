"""Generated privacy records stay complete, deterministic, and reviewable."""

from dataclasses import replace
from pathlib import Path

import pytest
from procuresignal.privacy.inventory import INVENTORY

from scripts.generate_privacy_docs import (
    check_documents,
    generated_documents,
    render_personal_data_inventory,
    render_processing_record,
)


def test_every_registry_table_appears_once_in_both_documents() -> None:
    """Dropping or duplicating a table would make the processing record dishonest."""

    inventory = render_personal_data_inventory(INVENTORY)
    record = render_processing_record(INVENTORY)

    for entry in INVENTORY:
        assert inventory.count(f"`{entry.table}`") == 1
        assert record.count(f"`{entry.table}`") == 1


def test_unknown_retention_is_stated_instead_of_rendered_blank() -> None:
    """A blank retention cell hides an unresolved policy decision."""

    rendered = render_personal_data_inventory((INVENTORY[0],))

    assert "No automatic expiry" in rendered


def test_markdown_inside_registry_text_cannot_break_generated_tables() -> None:
    """Registry prose is data and cannot create an extra Markdown column or row."""

    entry = replace(INVENTORY[0], purpose="Identity | authentication\nrecord")

    rendered = render_personal_data_inventory((entry,))

    assert "Identity \\| authentication record" in rendered


def test_markdown_inside_table_names_cannot_break_generated_tables() -> None:
    """Quoted SQL identifiers are still untrusted Markdown cell content."""

    entry = replace(INVENTORY[0], table="users|archive")

    inventory = render_personal_data_inventory((entry,))
    record = render_processing_record((entry,))

    assert "`users\\|archive`" in inventory
    assert "`users\\|archive`" in record


def test_processing_record_keeps_legal_decisions_visible() -> None:
    """Engineering must not silently invent the controller's legal position."""

    rendered = render_processing_record(INVENTORY)

    assert "OWNER INPUT REQUIRED" in rendered
    assert "Article 17(3)(b) and (e)" in rendered


def test_processing_record_derives_retention_exception_from_registry() -> None:
    """A regenerated document cannot preserve a superseded legal rationale."""

    audit = next(entry for entry in INVENTORY if entry.table == "audit_log")
    revised = replace(
        audit,
        retention_note="CUSTOM LEGAL REVIEW REQUIRED",
    )

    rendered = render_processing_record((revised,))

    assert "CUSTOM LEGAL REVIEW REQUIRED" in rendered
    assert "Article 17(3)(b) and (e)" not in rendered


def test_generation_is_byte_for_byte_reproducible() -> None:
    """Time, locale, and machine state cannot make CI report false drift."""

    assert generated_documents() == generated_documents()


def test_duplicate_table_names_are_rejected() -> None:
    """Two conflicting decisions for one table cannot both look authoritative."""

    with pytest.raises(RuntimeError, match="duplicate table names"):
        generated_documents((INVENTORY[0], INVENTORY[0]))


def test_check_reports_every_stale_document_without_rewriting_it(tmp_path: Path) -> None:
    """One stale file cannot hide the second, and check mode is read-only."""

    expected = {
        tmp_path / "inventory.md": "inventory\n",
        tmp_path / "record.md": "record\n",
    }
    for path in expected:
        path.write_text("stale\n")

    assert check_documents(expected) == sorted(expected)
    assert {path.read_text() for path in expected} == {"stale\n"}
