"""record which canonical suppliers a risk event affects

Revision ID: i3j4k5_add_risk_event_supplier_ids
Revises: h2i3j4_add_supplier_registry
"""

import sqlalchemy as sa
from alembic import op

revision = "i3j4k5_add_risk_event_supplier_ids"
down_revision = "h2i3j4_add_supplier_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive, beside the existing free-text affected_suppliers. Empty rather than
    # null so nothing has to special-case rows written before this.
    op.add_column(
        "risk_events",
        sa.Column("affected_supplier_ids", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("risk_events", "affected_supplier_ids")
