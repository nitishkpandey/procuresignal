"""add risk event scan tracking

Revision ID: e5f6a7_add_risk_event_scan_tracking
Revises: d4e5f6_add_risk_events
Create Date: 2026-07-12 16:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7_add_risk_event_scan_tracking"
down_revision = "d4e5f6_add_risk_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "news_articles_processed",
        sa.Column("risk_event_checked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_risk_event_scan_pending",
        "news_articles_processed",
        ["risk_event_checked_at", "processed_at"],
    )


def downgrade():
    op.drop_index("idx_risk_event_scan_pending", table_name="news_articles_processed")
    op.drop_column("news_articles_processed", "risk_event_checked_at")
