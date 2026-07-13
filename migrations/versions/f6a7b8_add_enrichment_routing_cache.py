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
    op.add_column("news_articles_processed", sa.Column("enrichment_policy_version", sa.String(100)))
    op.add_column("news_articles_processed", sa.Column("content_fingerprint", sa.String(255)))
    op.add_column("news_articles_processed", sa.Column("deterministic_confidence", sa.Float()))
    op.add_column(
        "news_articles_processed",
        sa.Column("llm_used", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    _consolidate_processed_duplicates()
    _create_processed_identity_constraint()
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
    op.create_index("idx_enrichment_cache_fingerprint", "enrichment_cache", ["content_fingerprint"])


def downgrade() -> None:
    _drop_processed_identity_constraint()
    op.drop_index("idx_enrichment_cache_fingerprint", table_name="enrichment_cache")
    op.drop_table("enrichment_cache")
    op.drop_column("news_articles_processed", "llm_used")
    op.drop_column("news_articles_processed", "deterministic_confidence")
    op.drop_column("news_articles_processed", "content_fingerprint")
    op.drop_column("news_articles_processed", "enrichment_policy_version")
    op.drop_column("news_articles_processed", "enrichment_reason")
    op.drop_column("news_articles_processed", "enrichment_method")


def _consolidate_processed_duplicates() -> None:
    """Repoint dependents before removing duplicate processed rows.

    None of the four dependent tables has a uniqueness constraint involving
    ``processed_article_id`` at the prior revision. Repointing therefore cannot
    create a database uniqueness collision, and preserving every dependent row
    retains match reasons, feed state, priority dispatch state, and risk events.
    """
    richness = " + ".join(
        f"CASE WHEN {column} IS NOT NULL THEN 1 ELSE 0 END"
        for column in (
            "signal_tags",
            "priority_signal",
            "detected_regions",
            "detected_suppliers",
            "detected_categories",
            "llm_model",
            "risk_event_checked_at",
            "enrichment_method",
            "enrichment_reason",
            "enrichment_policy_version",
            "content_fingerprint",
            "deterministic_confidence",
        )
    )
    op.execute(
        sa.text(
            "CREATE TEMPORARY TABLE enrichment_processed_duplicate_map AS "
            "SELECT id AS old_id, FIRST_VALUE(id) OVER ("
            "PARTITION BY raw_article_id ORDER BY "
            "CASE WHEN processing_status = 'completed' THEN 1 ELSE 0 END DESC, "
            f"({richness}) DESC, processed_at DESC, id DESC"
            ") AS survivor_id "
            "FROM news_articles_processed "
            "WHERE raw_article_id IN ("
            "SELECT raw_article_id FROM news_articles_processed "
            "GROUP BY raw_article_id HAVING COUNT(*) > 1)"
        )
    )
    for table in (
        "news_article_matches",
        "news_priority_events",
        "user_news_feed",
        "risk_events",
    ):
        op.execute(
            sa.text(
                f"UPDATE {table} SET processed_article_id = ("
                "SELECT survivor_id FROM enrichment_processed_duplicate_map "
                f"WHERE old_id = {table}.processed_article_id) "
                "WHERE processed_article_id IN ("
                "SELECT old_id FROM enrichment_processed_duplicate_map "
                "WHERE old_id <> survivor_id)"
            )
        )
    op.execute(
        sa.text(
            "DELETE FROM news_articles_processed WHERE id IN ("
            "SELECT old_id FROM enrichment_processed_duplicate_map "
            "WHERE old_id <> survivor_id)"
        )
    )
    op.execute(sa.text("DROP TABLE enrichment_processed_duplicate_map"))


def _create_processed_identity_constraint() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("news_articles_processed") as batch_op:
            batch_op.create_unique_constraint(
                "uq_news_articles_processed_raw_article_id", ["raw_article_id"]
            )
        return
    op.create_unique_constraint(
        "uq_news_articles_processed_raw_article_id",
        "news_articles_processed",
        ["raw_article_id"],
    )


def _drop_processed_identity_constraint() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("news_articles_processed") as batch_op:
            batch_op.drop_constraint("uq_news_articles_processed_raw_article_id", type_="unique")
        return
    op.drop_constraint(
        "uq_news_articles_processed_raw_article_id",
        "news_articles_processed",
        type_="unique",
    )
