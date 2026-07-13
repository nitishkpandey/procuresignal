"""add platform language preference

Revision ID: c3d4e5_add_platform_language
Revises: b2c3d4_signals_impact_areas_json
Create Date: 2026-07-09 13:20:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5_add_platform_language"
down_revision = "b2c3d4_signals_impact_areas_json"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_news_preferences",
        sa.Column(
            "platform_language",
            sa.String(length=10),
            nullable=False,
            server_default="en",
        ),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("user_news_preferences", "platform_language", server_default=None)


def downgrade():
    op.drop_column("user_news_preferences", "platform_language")
