"""Populated migration coverage for identity, tenancy, and audit tables."""

import importlib
from datetime import datetime

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

# Every table whose `user_id` column holds a legacy email identity.
LEGACY_TABLES = (
    "user_news_preferences",
    "user_news_feed",
    "chat_conversations",
    "chat_messages",
    "news_article_matches",
)


def _legacy_schema(engine: sa.Engine) -> sa.MetaData:
    metadata = sa.MetaData()
    for name in LEGACY_TABLES:
        sa.Table(
            name,
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
        )
    metadata.create_all(engine)
    return metadata


def test_legacy_identities_become_inactive_users_and_rows_follow(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    metadata = _legacy_schema(engine)

    with engine.begin() as connection:
        for index, name in enumerate(LEGACY_TABLES, start=1):
            connection.execute(
                metadata.tables[name].insert(),
                [
                    {"id": index * 10, "user_id": "buyer@acme.com"},
                    {"id": index * 10 + 1, "user_id": "lead@globex.com"},
                ],
            )

        migration = importlib.import_module("migrations.versions.g1h2i3_add_auth_tenancy_audit")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        users = connection.execute(
            sa.text("SELECT email, public_id, password_hash, is_active FROM users ORDER BY email")
        ).all()
        assert [u.email for u in users] == ["buyer@acme.com", "lead@globex.com"]

        for user in users:
            # Placeholders cannot be logged into, and must not keep the email as an identifier.
            assert user.password_hash is None
            assert not user.is_active
            assert user.public_id != user.email
            assert len(user.public_id) == 32

        by_email = {u.email: u.public_id for u in users}
        for name in LEGACY_TABLES:
            rows = (
                connection.execute(
                    sa.text(f"SELECT user_id FROM {name} ORDER BY id")  # noqa: S608 - fixed names
                )
                .scalars()
                .all()
            )
            assert rows == [by_email["buyer@acme.com"], by_email["lead@globex.com"]]

        # Each distinct legacy identity gets exactly one owning organization.
        memberships = connection.execute(sa.text("SELECT role FROM memberships")).scalars().all()
        assert memberships == ["owner", "owner"]


def test_upgrade_is_a_no_op_when_there_is_no_legacy_data(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)

    with engine.begin() as connection:
        migration = importlib.import_module("migrations.versions.g1h2i3_add_auth_tenancy_audit")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        assert connection.execute(sa.text("SELECT COUNT(*) FROM users")).scalar() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM audit_log")).scalar() == 0


def test_downgrade_drops_the_new_tables(monkeypatch) -> None:
    engine = sa.create_engine("sqlite://")
    _legacy_schema(engine)

    with engine.begin() as connection:
        migration = importlib.import_module("migrations.versions.g1h2i3_add_auth_tenancy_audit")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO refresh_tokens "
                "(user_id, token_hash, family_id, expires_at, created_at, updated_at) "
                "VALUES (1, 'h', 'f', :now, :now, :now)"
            ),
            {"now": datetime.utcnow()},
        )
        migration.downgrade()

        remaining = set(sa.inspect(connection).get_table_names())
        assert not remaining & {
            "users",
            "organizations",
            "memberships",
            "refresh_tokens",
            "audit_log",
        }
