"""The audit trail must be append-only in the database, not by convention."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = "migrations.versions.k5l6m7_audit_immutable"


def _audit_table(engine: sa.Engine) -> sa.Table:
    metadata = sa.MetaData()
    table = sa.Table(
        "audit_log",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
    )
    metadata.create_all(engine)
    return table


def _apply(connection, monkeypatch, direction: str = "upgrade") -> None:
    migration = importlib.import_module(MIGRATION)
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    getattr(migration, direction)()


def test_recorded_actions_cannot_be_altered(monkeypatch) -> None:
    """Application code being careful is not the same as the database refusing."""
    engine = sa.create_engine("sqlite://")
    table = _audit_table(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), {"id": 1, "action": "user.login", "outcome": "success"})
        _apply(connection, monkeypatch)

        with pytest.raises(sa.exc.DatabaseError):
            connection.execute(sa.text("UPDATE audit_log SET outcome = 'failure' WHERE id = 1"))


def test_recorded_actions_cannot_be_deleted(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    table = _audit_table(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), {"id": 1, "action": "user.login", "outcome": "success"})
        _apply(connection, monkeypatch)

        with pytest.raises(sa.exc.DatabaseError):
            connection.execute(sa.text("DELETE FROM audit_log WHERE id = 1"))


def test_new_records_are_still_accepted(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    table = _audit_table(engine)

    with engine.begin() as connection:
        _apply(connection, monkeypatch)
        connection.execute(table.insert(), {"id": 2, "action": "user.login", "outcome": "success"})

        rows = connection.execute(sa.text("SELECT COUNT(*) FROM audit_log")).scalar()
        assert rows == 1


def test_downgrade_removes_the_triggers(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    table = _audit_table(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), {"id": 1, "action": "a", "outcome": "success"})
        _apply(connection, monkeypatch)
        _apply(connection, monkeypatch, direction="downgrade")

        connection.execute(sa.text("DELETE FROM audit_log WHERE id = 1"))
