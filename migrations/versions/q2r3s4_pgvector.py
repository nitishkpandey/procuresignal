"""enable pgvector

Revision ID: q2r3s4_pgvector
Revises: p0q1r2_notifications

Phase 5 stores article embeddings in a `vector` column. The extension has to exist before
any migration can declare that type, so it is enabled on its own rather than bundled with
the table that needs it — a failed CREATE EXTENSION halfway through a table creation is a
harder state to reason about than a migration that does one thing.

Guarded on the dialect: the test suite and local development also run on SQLite, where
this statement is meaningless and would abort the upgrade.
"""

from alembic import op

revision = "q2r3s4_pgvector"
down_revision = "p0q1r2_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Not dropped. Other databases in the cluster may share the extension, and dropping it
    # would cascade away every vector column rather than fail loudly.
    pass
