"""add risk events

Revision ID: d4e5f6_add_risk_events
Revises: c3d4e5_add_platform_language
Create Date: 2026-07-12 14:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6_add_risk_events"
down_revision = "c3d4e5_add_platform_language"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "risk_events",
        sa.Column("event_key", sa.String(length=500), nullable=False),
        sa.Column("processed_article_id", sa.Integer(), nullable=False),
        sa.Column("risk_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("affected_suppliers", sa.JSON(), nullable=False),
        sa.Column("affected_locations", sa.JSON(), nullable=False),
        sa.Column("affected_categories", sa.JSON(), nullable=False),
        sa.Column("evidence_snippet", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_risk_events_event_key"),
    )
    op.create_index("idx_risk_events_processed_article_id", "risk_events", ["processed_article_id"])
    op.create_index("idx_risk_events_type_status", "risk_events", ["risk_type", "status"])
    op.create_index("idx_risk_events_severity", "risk_events", ["severity"])
    op.create_index("idx_risk_events_published_at", "risk_events", ["published_at"])


def downgrade():
    op.drop_index("idx_risk_events_published_at", table_name="risk_events")
    op.drop_index("idx_risk_events_severity", table_name="risk_events")
    op.drop_index("idx_risk_events_type_status", table_name="risk_events")
    op.drop_index("idx_risk_events_processed_article_id", table_name="risk_events")
    op.drop_table("risk_events")
