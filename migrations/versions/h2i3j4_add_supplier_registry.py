"""add supplier registry, aliases, and article mentions

Revision ID: h2i3j4_add_supplier_registry
Revises: g1h2i3_add_auth_tenancy_audit
"""

import sqlalchemy as sa
from alembic import op

revision = "h2i3j4_add_supplier_registry"
down_revision = "g1h2i3_add_auth_tenancy_audit"
branch_labels = None
depends_on = None

RESOLVED_ID_COLUMNS = ("preferred_supplier_ids", "excluded_supplier_ids")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("canonical_name", sa.String(300), nullable=False),
        # Retains the legal form, which is what keeps "Siemens AG" and
        # "Siemens Energy AG" apart. The stripped spelling becomes an alias instead.
        sa.Column("normalized_name", sa.String(300), nullable=False, unique=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("lei", sa.String(20), nullable=True, unique=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
    )
    op.create_index("idx_suppliers_normalized", "suppliers", ["normalized_name"])

    op.create_table(
        "supplier_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(300), nullable=False),
        # Globally unique: two suppliers claiming one spelling must fail here, where an
        # operator can decide, rather than resolving to whichever row is found first.
        sa.Column("normalized_alias", sa.String(300), nullable=False, unique=True),
        sa.Column("source", sa.String(20), server_default="manual", nullable=False),
        *_timestamps(),
    )
    op.create_index("idx_alias_normalized", "supplier_aliases", ["normalized_alias"])
    op.create_index("idx_alias_supplier", "supplier_aliases", ["supplier_id"])

    op.create_table(
        "article_supplier_mentions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("processed_article_id", sa.Integer(), nullable=False),
        # Null when the name did not resolve. The row is kept regardless: it is what
        # tells an operator which alias is missing.
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("surface_form", sa.String(300), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "processed_article_id", "surface_form", name="uq_mention_article_surface"
        ),
    )
    op.create_index("idx_mention_supplier", "article_supplier_mentions", ["supplier_id"])
    op.create_index("idx_mention_article", "article_supplier_mentions", ["processed_article_id"])

    # Additive. Existing rows get an empty list rather than null, so every reader can
    # treat the column as a list without a special case for pre-migration data.
    for column in RESOLVED_ID_COLUMNS:
        op.add_column(
            "user_news_preferences",
            sa.Column(column, sa.JSON(), server_default="[]", nullable=False),
        )


def downgrade() -> None:
    """Fully reversible: no existing column is rewritten by the upgrade."""

    for column in RESOLVED_ID_COLUMNS:
        op.drop_column("user_news_preferences", column)

    for index, table in (
        ("idx_mention_article", "article_supplier_mentions"),
        ("idx_mention_supplier", "article_supplier_mentions"),
        ("idx_alias_supplier", "supplier_aliases"),
        ("idx_alias_normalized", "supplier_aliases"),
        ("idx_suppliers_normalized", "suppliers"),
    ):
        op.drop_index(index, table_name=table)

    for table in ("article_supplier_mentions", "supplier_aliases", "suppliers"):
        op.drop_table(table)
