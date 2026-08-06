"""track llm spend per tenant per day

Revision ID: m7n8o9_llm_spend
Revises: l6m7n8_dead_letters
"""

import sqlalchemy as sa
from alembic import op

revision = "m7n8o9_llm_spend"
down_revision = "l6m7n8_dead_letters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_spend",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("spend_date", sa.Date(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("calls_made", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant", "spend_date", name="uq_llm_spend_tenant_day"),
    )
    op.create_index("idx_llm_spend_day", "llm_spend", ["spend_date"])


def downgrade() -> None:
    op.drop_index("idx_llm_spend_day", table_name="llm_spend")
    op.drop_table("llm_spend")
