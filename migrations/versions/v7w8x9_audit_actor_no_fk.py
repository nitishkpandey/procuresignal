"""let an account be deleted while its audit trail stays put

Revision ID: v7w8x9_audit_actor_no_fk
Revises: u6v7w8_agent_runs

Erasure was impossible. `audit_log.actor_user_id` referenced `users.id` with ON DELETE
SET NULL, and `audit_log` carries a BEFORE UPDATE trigger that raises — so a cascade
setting the column to NULL is an UPDATE the database refuses. Deleting any user who had
ever signed in failed with "audit_log is append-only; UPDATE is not permitted".

Nothing in the suite could have caught it: SQLite has foreign keys off by default, so
the cascade never fired there, and no test deleted a user on PostgreSQL.

expand/contract: dropping a foreign key removes a constraint and nothing else. The
running release keeps writing `actor_user_id` exactly as before and no query reads it
through the constraint, so old and new pods coexist safely. The column and its index
stay.

Losing referential integrity here is the point rather than a cost. An append-only table
must not be mutated by anything, including a cascade, and `actor_email` is already
denormalised onto the row precisely so the trail still names the actor once the account
is gone. What remains after an erasure is an integer pointing at a user who no longer
exists — which is what an immutable record of a past event should say.
"""

from alembic import op

revision = "v7w8x9_audit_actor_no_fk"
down_revision = "u6v7w8_agent_runs"
branch_labels = None
depends_on = None

CONSTRAINT = "audit_log_actor_user_id_fkey"


def upgrade() -> None:
    # SQLite would need a table rebuild to drop a constraint, and the constraint is
    # unenforced there anyway. The dialect that has the problem is the one that ships.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint(CONSTRAINT, "audit_log", type_="foreignkey")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Restores the constraint, and with it the bug: deleting a user with audit entries
    # will fail again. Reversible because a migration that cannot be rolled back turns a
    # bad deploy into a restore, not because going back is a good idea.
    op.create_foreign_key(
        CONSTRAINT,
        "audit_log",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
