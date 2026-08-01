"""add identity, tenancy, sessions, and audit trail

Revision ID: g1h2i3_add_auth_tenancy_audit
Revises: f8c9d0_add_retrieval_source_audit
"""

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "g1h2i3_add_auth_tenancy_audit"
down_revision = "f8c9d0_add_retrieval_source_audit"
branch_labels = None
depends_on = None

# Tables whose `user_id` column holds an identity string that the backfill rewrites.
LEGACY_TABLES = (
    "user_news_preferences",
    "user_news_feed",
    "chat_conversations",
    "chat_messages",
    "news_article_matches",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _slug(email: str) -> str:
    domain = email.partition("@")[2] or email
    cleaned = "".join(char if char.isalnum() else "-" for char in domain.lower()).strip("-")
    return cleaned or "organization"


def _create_tables() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        *_timestamps(),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        *_timestamps(),
    )
    op.create_index("idx_users_email", "users", ["email"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), server_default="member", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
    )
    op.create_index("idx_membership_user", "memberships", ["user_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        *_timestamps(),
    )
    op.create_index("idx_refresh_user", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_family", "refresh_tokens", ["family_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=True),
        sa.Column("resource_id", sa.String(200), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        *_timestamps(),
    )
    op.create_index("idx_audit_org_created", "audit_log", ["organization_id", "created_at"])
    op.create_index("idx_audit_actor", "audit_log", ["actor_user_id"])
    op.create_index("idx_audit_action", "audit_log", ["action"])


def _existing_tables(connection: sa.Connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _backfill_identities(connection: sa.Connection) -> None:
    """Give every legacy identity string a placeholder user, then repoint the rows at it.

    Placeholders are created inactive and without a password, so nobody can log in as one.
    Registration deliberately does not claim them: letting a signup adopt a placeholder by
    matching its email would hand over that person's feed and chat history.
    """
    present = [name for name in LEGACY_TABLES if name in _existing_tables(connection)]
    if not present:
        return

    union = " UNION ".join(f"SELECT user_id FROM {name}" for name in present)  # noqa: S608
    identities = sorted(
        value
        for value in connection.execute(sa.text(union)).scalars().all()
        if value is not None and value != ""
    )
    if not identities:
        return

    now = datetime.utcnow()
    for identity in identities:
        organization_public_id = uuid4().hex
        connection.execute(
            sa.text(
                "INSERT INTO organizations (public_id, name, slug, created_at, updated_at) "
                "VALUES (:public_id, :name, :slug, :now, :now)"
            ),
            {
                "public_id": organization_public_id,
                "name": identity,
                "slug": f"{_slug(identity)}-{organization_public_id[:8]}",
                "now": now,
            },
        )
        organization_id = connection.execute(
            sa.text("SELECT id FROM organizations WHERE public_id = :public_id"),
            {"public_id": organization_public_id},
        ).scalar_one()

        user_public_id = uuid4().hex
        connection.execute(
            sa.text(
                "INSERT INTO users "
                "(public_id, email, password_hash, is_active, token_version, "
                " created_at, updated_at) "
                "VALUES (:public_id, :email, NULL, :inactive, 0, :now, :now)"
            ),
            {
                "public_id": user_public_id,
                "email": identity,
                "inactive": False,
                "now": now,
            },
        )
        user_id = connection.execute(
            sa.text("SELECT id FROM users WHERE public_id = :public_id"),
            {"public_id": user_public_id},
        ).scalar_one()

        connection.execute(
            sa.text(
                "INSERT INTO memberships "
                "(user_id, organization_id, role, created_at, updated_at) "
                "VALUES (:user_id, :organization_id, 'owner', :now, :now)"
            ),
            {
                "user_id": user_id,
                "organization_id": organization_id,
                "now": now,
            },
        )

        for name in present:
            connection.execute(
                sa.text(f"UPDATE {name} SET user_id = :new WHERE user_id = :old"),  # noqa: S608
                {"new": user_public_id, "old": identity},
            )


def upgrade() -> None:
    _create_tables()
    _backfill_identities(op.get_bind())


def downgrade() -> None:
    """Drop the identity tables.

    The legacy `user_id` rewrite is NOT reversed. The mapping from public id back to the
    original email lives only in the `users` table this drops, so reversing it would need a
    backup taken before the upgrade.
    """
    for index, table in (
        ("idx_audit_action", "audit_log"),
        ("idx_audit_actor", "audit_log"),
        ("idx_audit_org_created", "audit_log"),
        ("idx_refresh_family", "refresh_tokens"),
        ("idx_refresh_user", "refresh_tokens"),
        ("idx_membership_user", "memberships"),
        ("idx_users_email", "users"),
    ):
        op.drop_index(index, table_name=table)

    for table in ("audit_log", "refresh_tokens", "memberships", "users", "organizations"):
        op.drop_table(table)
