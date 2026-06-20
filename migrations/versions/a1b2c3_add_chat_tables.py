"""add chat tables

Revision ID: a1b2c3_add_chat_tables
Revises: 1a2b3c_add_signals_tables
Create Date: 2026-06-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3_add_chat_tables"
down_revision = "1a2b3c_add_signals_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("conversation_id", name="uq_chat_conversations_conversation_id"),
    )
    op.create_index(
        "idx_chat_conversations_user_last",
        "chat_conversations",
        ["user_id", "last_message_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "idx_chat_messages_conv_created",
        "chat_messages",
        ["conversation_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_chat_messages_conv_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("idx_chat_conversations_user_last", table_name="chat_conversations")
    op.drop_table("chat_conversations")
