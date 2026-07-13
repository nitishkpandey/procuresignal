"""convert signals.impact_areas from text[] to json

The Signal model maps impact_areas as JSON (portable across Postgres/SQLite,
consistent with the other list columns), but the original migration created it
as text[], so ORM inserts failed with a datatype mismatch. Align the column.

Revision ID: b2c3d4_signals_impact_areas_json
Revises: a1b2c3_add_chat_tables
Create Date: 2026-07-03 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b2c3d4_signals_impact_areas_json"
down_revision = "a1b2c3_add_chat_tables"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "signals",
        "impact_areas",
        type_=sa.JSON(),
        postgresql_using="array_to_json(impact_areas)",
    )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "signals",
        "impact_areas",
        type_=postgresql.ARRAY(sa.Text()),
        postgresql_using="ARRAY(SELECT json_array_elements_text(impact_areas))",
    )
