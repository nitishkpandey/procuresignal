"""add organization invitations

Revision ID: j4k5l6_org_invitations
Revises: i3j4k5_risk_supplier_ids
"""

import sqlalchemy as sa
from alembic import op

revision = "j4k5l6_org_invitations"
down_revision = "i3j4k5_risk_supplier_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), server_default="member", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_invitation_email", "organization_invitations", ["email"])
    op.create_index("idx_invitation_organization", "organization_invitations", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_invitation_organization", table_name="organization_invitations")
    op.drop_index("idx_invitation_email", table_name="organization_invitations")
    op.drop_table("organization_invitations")
