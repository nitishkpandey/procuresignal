"""Populated migration coverage for the supplier registry."""

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = "migrations.versions.h2i3j4_add_supplier_registry"
NEW_TABLES = {"suppliers", "supplier_aliases", "article_supplier_mentions"}


def _legacy_preferences(engine: sa.Engine) -> sa.Table:
    metadata = sa.MetaData()
    preferences = sa.Table(
        "user_news_preferences",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("preferred_suppliers", sa.JSON, nullable=False),
        sa.Column("excluded_suppliers", sa.JSON, nullable=False),
    )
    metadata.create_all(engine)
    return preferences


def _apply(connection, monkeypatch, direction: str = "upgrade") -> None:
    migration = importlib.import_module(MIGRATION)
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    getattr(migration, direction)()


def test_existing_preferences_survive_with_empty_resolved_ids(monkeypatch) -> None:
    """A preference row written before this phase must remain valid and readable."""
    engine = sa.create_engine("sqlite://")
    preferences = _legacy_preferences(engine)

    with engine.begin() as connection:
        connection.execute(
            preferences.insert(),
            {
                "id": 1,
                "user_id": "u1",
                "preferred_suppliers": ["Bosch"],
                "excluded_suppliers": [],
            },
        )
        _apply(connection, monkeypatch)

        row = connection.execute(
            sa.text(
                "SELECT preferred_suppliers, preferred_supplier_ids, excluded_supplier_ids "
                "FROM user_news_preferences WHERE id = 1"
            )
        ).one()

        # The text the user typed is untouched.
        assert "Bosch" in str(row.preferred_suppliers)
        # The new columns default to empty rather than null, so readers need no special case.
        assert str(row.preferred_supplier_ids) in ("[]", "'[]'")
        assert str(row.excluded_supplier_ids) in ("[]", "'[]'")


def test_registry_tables_are_created(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    _legacy_preferences(engine)

    with engine.begin() as connection:
        _apply(connection, monkeypatch)
        assert NEW_TABLES <= set(sa.inspect(connection).get_table_names())


def test_alias_uniqueness_is_enforced_by_the_schema(monkeypatch) -> None:
    """The constraint is the whole safety argument, so the migration must create it."""
    engine = sa.create_engine("sqlite://")
    _legacy_preferences(engine)

    with engine.begin() as connection:
        _apply(connection, monkeypatch)
        connection.execute(
            sa.text(
                "INSERT INTO suppliers "
                "(id, public_id, canonical_name, normalized_name, is_active, "
                " created_at, updated_at) "
                "VALUES (1,'s1','Apple Inc','apple inc',1,'2026-08-01','2026-08-01'), "
                "       (2,'s2','Apple Bank','apple bank',1,'2026-08-01','2026-08-01')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO supplier_aliases "
                "(supplier_id, alias, normalized_alias, source, created_at, updated_at) "
                "VALUES (1,'Apple','apple','derived','2026-08-01','2026-08-01')"
            )
        )

        try:
            connection.execute(
                sa.text(
                    "INSERT INTO supplier_aliases "
                    "(supplier_id, alias, normalized_alias, source, created_at, updated_at) "
                    "VALUES (2,'Apple','apple','derived','2026-08-01','2026-08-01')"
                )
            )
        except sa.exc.IntegrityError:
            pass
        else:  # pragma: no cover - only reached if the constraint is missing
            raise AssertionError("a second supplier was allowed to claim the same alias")


def test_downgrade_removes_everything_it_added(monkeypatch) -> None:
    """Nothing existing is rewritten, so this migration is fully reversible."""
    engine = sa.create_engine("sqlite://")
    _legacy_preferences(engine)

    with engine.begin() as connection:
        _apply(connection, monkeypatch)
        _apply(connection, monkeypatch, direction="downgrade")

        inspector = sa.inspect(connection)
        assert not NEW_TABLES & set(inspector.get_table_names())

        columns = {column["name"] for column in inspector.get_columns("user_news_preferences")}
        assert "preferred_supplier_ids" not in columns
        assert "preferred_suppliers" in columns
