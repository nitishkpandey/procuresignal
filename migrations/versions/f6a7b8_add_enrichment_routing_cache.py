"""add enrichment routing metadata and cache

Revision ID: f6a7b8_add_enrichment_routing_cache
Revises: e5f6a7_add_risk_event_scan_tracking
Create Date: 2026-07-13 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8_add_enrichment_routing_cache"
down_revision = "e5f6a7_add_risk_event_scan_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_articles_processed", sa.Column("enrichment_method", sa.String(20)))
    op.add_column("news_articles_processed", sa.Column("enrichment_reason", sa.String(100)))
    op.add_column(
        "news_articles_processed", sa.Column("enrichment_policy_version", sa.String(100))
    )
    op.add_column("news_articles_processed", sa.Column("content_fingerprint", sa.String(255)))
    op.add_column(
        "news_articles_processed", sa.Column("deterministic_confidence", sa.Float())
    )
    op.add_column(
        "news_articles_processed",
        sa.Column("llm_used", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "enrichment_cache",
        sa.Column("content_fingerprint", sa.String(255), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("original_method", sa.String(20), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "original_method IN ('deterministic', 'llm')",
            name="ck_enrichment_cache_original_method",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_fingerprint",
            "policy_version",
            "taxonomy_version",
            name="uq_enrichment_cache_identity",
        ),
    )
    op.create_index(
        "idx_enrichment_cache_fingerprint", "enrichment_cache", ["content_fingerprint"]
    )


def downgrade() -> None:
    op.drop_index("idx_enrichment_cache_fingerprint", table_name="enrichment_cache")
    op.drop_table("enrichment_cache")
    op.drop_column("news_articles_processed", "llm_used")
    op.drop_column("news_articles_processed", "deterministic_confidence")
    op.drop_column("news_articles_processed", "content_fingerprint")
    op.drop_column("news_articles_processed", "enrichment_policy_version")
    op.drop_column("news_articles_processed", "enrichment_reason")
    op.drop_column("news_articles_processed", "enrichment_method")
