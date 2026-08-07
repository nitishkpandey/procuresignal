"""add organization-scoped supplier watchlists

Revision ID: n8o9p0_watchlists
Revises: m7n8o9_llm_spend
"""

import sqlalchemy as sa
from alembic import op

revision = "n8o9p0_watchlists"
down_revision = "m7n8o9_llm_spend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Per organization, not global: every team calls one of them "Tier 1".
        sa.UniqueConstraint("organization_id", "normalized_name", name="uq_watchlist_org_name"),
    )
    op.create_index("idx_watchlist_organization", "watchlists", ["organization_id"])

    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("watchlist_id", "supplier_id", name="uq_watchlist_entry"),
    )
    op.create_index("idx_watchlist_entry_supplier", "watchlist_entries", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("idx_watchlist_entry_supplier", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
    op.drop_index("idx_watchlist_organization", table_name="watchlists")
    op.drop_table("watchlists")
