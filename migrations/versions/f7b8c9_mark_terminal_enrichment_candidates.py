"""mark terminal enrichment candidates

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
    op.add_column(
        "news_articles_raw", sa.Column("enrichment_terminal_status", sa.String(20), nullable=True)
    )
    op.create_index(
        "idx_raw_enrichment_terminal_status",
        "news_articles_raw",
        ["enrichment_terminal_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_raw_enrichment_terminal_status", table_name="news_articles_raw")
    op.drop_column("news_articles_raw", "enrichment_terminal_status")
