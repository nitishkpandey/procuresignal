"""add signals tables

Revision ID: 1a2b3c_add_signals_tables
Revises: 1f8f95ad327b
Create Date: 2026-05-14 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1a2b3c_add_signals_tables"
down_revision = "1f8f95ad327b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("impact_areas", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("raw_signal", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "signal_metadata",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=255), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "signal_supply_chain_impact",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("affected_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relationship_type", sa.String(length=100), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade():
    op.drop_table("signal_supply_chain_impact")
    op.drop_table("signal_metadata")
    op.drop_table("signals")
