"""relevance feedback capture

Revision ID: t5u6v7_search_feedback
Revises: s4t5u6_article_embeddings

What a user did with a search result, kept so learning-to-rank has data when it is worth
building. `rank_position` and `mode` are the columns that make it trainable: a click on
result 1 and a click on result 9 say opposite things about the ranker.

Unique on (user_id, query_fingerprint, processed_article_id, signal) so a double-click is
one label rather than two.

`processed_article_id` carries no foreign key on purpose. Retention prunes processed
articles after 30 days, and cascading would cap the training set at 30 days of feedback,
which can never support a train/test split. Validated by the endpoint instead.

`query_text` is user-entered content tied to an identified person. This table is in scope
for Phase 7's erasure path, recorded in docs/personal-data-inventory.md.
"""

import sqlalchemy as sa
from alembic import op

revision = "t5u6v7_search_feedback"
down_revision = "s4t5u6_article_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.String(length=200), nullable=False),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("processed_article_id", sa.Integer(), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("signal", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "query_fingerprint",
            "processed_article_id",
            "signal",
            name="uq_search_feedback_signal",
        ),
    )
    op.create_index("idx_search_feedback_organization", "search_feedback", ["organization_id"])
    op.create_index("idx_search_feedback_fingerprint", "search_feedback", ["query_fingerprint"])


def downgrade() -> None:
    op.drop_index("idx_search_feedback_fingerprint", table_name="search_feedback")
    op.drop_index("idx_search_feedback_organization", table_name="search_feedback")
    op.drop_table("search_feedback")
