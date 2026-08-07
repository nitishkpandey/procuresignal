"""add organization alert rules

Revision ID: o9p0q1_alert_rules
Revises: n8o9p0_watchlists
"""

import sqlalchemy as sa
from alembic import op

revision = "o9p0q1_alert_rules"
down_revision = "n8o9p0_watchlists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
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
        # Inclusive floor: a critical event satisfies a rule set to high.
        sa.Column("min_severity", sa.String(20), server_default="high", nullable=False),
        # Empty means every type; listing them all would go stale as the taxonomy grows.
        sa.Column("risk_types", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "normalized_name", name="uq_alert_rule_org_name"),
    )
    op.create_index("idx_alert_rule_organization", "alert_rules", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_alert_rule_organization", table_name="alert_rules")
    op.drop_table("alert_rules")
