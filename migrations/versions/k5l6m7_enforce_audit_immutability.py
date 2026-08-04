"""make the audit trail append-only in the database

Revision ID: k5l6m7_enforce_audit_immutability
Revises: j4k5l6_add_organization_invitations
"""

import sqlalchemy as sa
from alembic import op

revision = "k5l6m7_enforce_audit_immutability"
down_revision = "j4k5l6_add_organization_invitations"
branch_labels = None
depends_on = None

# Application convention is not immutability: any future handler, migration, or
# console session can UPDATE or DELETE an audit row. These triggers make the database
# refuse, so tampering needs a deliberate schema change that is itself visible.
#
# Not the whole story for a compliance audit — that wants an append-only sink outside
# this database, and a role that lacks TRIGGER and ALTER on the table. This closes the
# accidental and casual cases, which is what is achievable before hosting is chosen.
_POSTGRES = [
    """
    CREATE OR REPLACE FUNCTION audit_log_is_append_only() RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only; % is not permitted', TG_OP;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();
    """,
    """
    CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();
    """,
]

_SQLITE = [
    """
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    """,
    """
    CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    """,
]


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for statement in _POSTGRES if dialect == "postgresql" else _SQLITE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS audit_log_is_append_only()"))
    else:
        op.execute(sa.text("DROP TRIGGER IF EXISTS audit_log_no_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS audit_log_no_delete"))
