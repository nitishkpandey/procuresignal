"""add the notification outbox

Revision ID: p0q1r2_notifications
Revises: o9p0q1_alert_rules
"""

import sqlalchemy as sa
from alembic import op

revision = "p0q1r2_notifications"
down_revision = "o9p0q1_alert_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alert_rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "risk_event_id",
            sa.Integer(),
            sa.ForeignKey("risk_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(20), server_default="in_app", nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("supplier_public_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # The idempotency key. Rules are evaluated on a schedule and see the same event
        # repeatedly; this is what stops a re-run re-notifying, enforced here rather
        # than by a query-then-insert that races itself.
        sa.UniqueConstraint(
            "alert_rule_id",
            "risk_event_id",
            "recipient_user_id",
            "channel",
            name="uq_notification_idempotency",
        ),
    )
    op.create_index("idx_notification_recipient", "notifications", ["recipient_user_id", "read_at"])
    op.create_index("idx_notification_status", "notifications", ["status"])


def downgrade() -> None:
    op.drop_index("idx_notification_status", table_name="notifications")
    op.drop_index("idx_notification_recipient", table_name="notifications")
    op.drop_table("notifications")
