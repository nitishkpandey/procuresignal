"""add retrieval provenance and source audit

Revision ID: f8c9d0_add_retrieval_source_audit
Revises: f7b8c9_terminal_enrichment
"""

import sqlalchemy as sa
from alembic import op

revision = "f8c9d0_add_retrieval_source_audit"
down_revision = "f7b8c9_terminal_enrichment"
branch_labels = None
depends_on = None


def _counts() -> list[sa.Column]:
    return [
        sa.Column(name, sa.Integer(), server_default="0", nullable=False)
        for name in (
            "attempted_count",
            "fetched_count",
            "accepted_count",
            "inserted_count",
            "duplicate_count",
            "rejected_count",
            "failed_count",
        )
    ]


def upgrade() -> None:
    op.add_column("news_articles_raw", sa.Column("source_id", sa.String(255), nullable=True))
    op.add_column("news_articles_raw", sa.Column("source_class", sa.String(50), nullable=True))
    op.add_column("news_articles_raw", sa.Column("source_domains", sa.JSON(), nullable=True))
    op.add_column("news_articles_raw", sa.Column("source_countries", sa.JSON(), nullable=True))
    op.add_column("news_articles_raw", sa.Column("registry_version", sa.String(255), nullable=True))
    op.add_column("news_articles_raw", sa.Column("retrieved_at", sa.DateTime(), nullable=True))
    op.add_column(
        "news_articles_raw", sa.Column("source_published_at_raw", sa.String(255), nullable=True)
    )
    op.create_index("idx_raw_source_id", "news_articles_raw", ["source_id"])

    op.create_table(
        "news_retrieval_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("registry_version", sa.String(255), nullable=False),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        *_counts(),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_news_retrieval_runs_run_key"),
    )
    op.create_index(
        "idx_retrieval_run_status_lease", "news_retrieval_runs", ["status", "lease_expires_at"]
    )
    op.create_table(
        "news_retrieval_source_outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        *_counts(),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("failure_code", sa.String(50), nullable=True),
        sa.Column("outcome_detail", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["news_retrieval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_id", name="uq_retrieval_outcome_run_source"),
    )
    op.create_index(
        "idx_retrieval_outcome_source_started",
        "news_retrieval_source_outcomes",
        ["source_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_retrieval_outcome_source_started", table_name="news_retrieval_source_outcomes"
    )
    op.drop_table("news_retrieval_source_outcomes")
    op.drop_index("idx_retrieval_run_status_lease", table_name="news_retrieval_runs")
    op.drop_table("news_retrieval_runs")
    op.drop_index("idx_raw_source_id", table_name="news_articles_raw")
    for column in (
        "source_published_at_raw",
        "retrieved_at",
        "registry_version",
        "source_countries",
        "source_domains",
        "source_class",
        "source_id",
    ):
        op.drop_column("news_articles_raw", column)
