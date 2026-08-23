"""article embeddings

Revision ID: s4t5u6_article_embeddings
Revises: r3s4t5_article_fts

One row per article per embedding model, unique on the pair so the backfill is
idempotent under a re-run and under two workers racing each other — an application-level
check would pass in both processes and still write twice.

The vector column is declared without a fixed width. `text-embedding-3-large` is 3072
dimensions, and `vector(1536)` would make adopting it a table rewrite rather than a
configuration change; `dimensions` records what each row holds. The cost is that no
ivfflat or hnsw index can be built, which needs a fixed width — acceptable while the
corpus is bounded by the 30-day retention policy and exact scan is fast enough. D4's
revisit trigger is 10M vectors or a p99 above 200ms, both far above that.

ON DELETE CASCADE rather than another line in the retention job: embeddings whose
article has been pruned would grow without bound and rank results that no longer exist.

On SQLite the column becomes JSON so development and the in-memory suite still run; the
distance operators only exist on PostgreSQL and are tested there.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "s4t5u6_article_embeddings"
down_revision = "r3s4t5_article_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "processed_article_id",
            sa.Integer(),
            sa.ForeignKey("news_articles_processed.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.UniqueConstraint("processed_article_id", "model", name="uq_article_embedding_model"),
    )
    # Every query filters by the active model before it computes a distance.
    op.create_index("idx_article_embeddings_model", "article_embeddings", ["model"])


def downgrade() -> None:
    op.drop_index("idx_article_embeddings_model", table_name="article_embeddings")
    op.drop_table("article_embeddings")
