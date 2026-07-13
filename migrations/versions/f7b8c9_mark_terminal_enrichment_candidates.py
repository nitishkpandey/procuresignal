"""add enrichment candidate lifecycle

Revision ID: f7b8c9_terminal_enrichment
Revises: f6a7b8_add_enrichment_routing_cache
"""

import sqlalchemy as sa
from alembic import op

revision = "f7b8c9_terminal_enrichment"
down_revision = "f6a7b8_add_enrichment_routing_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_articles_raw", sa.Column("enrichment_status", sa.String(30), nullable=True))
    op.add_column(
        "news_articles_raw",
        sa.Column("enrichment_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "news_articles_raw", sa.Column("enrichment_next_attempt_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "news_articles_raw", sa.Column("enrichment_lease_owner", sa.String(100), nullable=True)
    )
    op.add_column(
        "news_articles_raw", sa.Column("enrichment_lease_expires_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "idx_raw_enrichment_lifecycle",
        "news_articles_raw",
        ["enrichment_status", "enrichment_next_attempt_at"],
    )
    op.create_index(
        "idx_raw_enrichment_lease",
        "news_articles_raw",
        ["enrichment_lease_expires_at", "enrichment_lease_owner"],
    )


def downgrade() -> None:
    op.drop_index("idx_raw_enrichment_lease", table_name="news_articles_raw")
    op.drop_index("idx_raw_enrichment_lifecycle", table_name="news_articles_raw")
    op.drop_column("news_articles_raw", "enrichment_lease_expires_at")
    op.drop_column("news_articles_raw", "enrichment_lease_owner")
    op.drop_column("news_articles_raw", "enrichment_next_attempt_at")
    op.drop_column("news_articles_raw", "enrichment_attempt_count")
    op.drop_column("news_articles_raw", "enrichment_status")
