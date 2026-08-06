"""record tasks that exhausted their retries

Revision ID: l6m7n8_dead_letters
Revises: k5l6m7_audit_immutable
"""

import sqlalchemy as sa
from alembic import op

revision = "l6m7n8_dead_letters"
down_revision = "k5l6m7_audit_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_name", sa.String(200), nullable=False),
        sa.Column("task_id", sa.String(200), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(200), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_dead_letter_task", "dead_letters", ["task_name"])
    op.create_index("idx_dead_letter_created", "dead_letters", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_dead_letter_created", table_name="dead_letters")
    op.drop_index("idx_dead_letter_task", table_name="dead_letters")
    op.drop_table("dead_letters")
