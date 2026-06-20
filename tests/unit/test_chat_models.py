"""Tests for chat models."""

from procuresignal.models import ChatConversation, ChatMessage


def test_chat_conversation_table_and_columns():
    assert ChatConversation.__tablename__ == "chat_conversations"
    cols = {c.name for c in ChatConversation.__table__.columns}
    assert {
        "id",
        "user_id",
        "conversation_id",
        "title",
        "message_count",
        "last_message_at",
        "created_at",
        "updated_at",
    } <= cols


def test_chat_conversation_id_is_unique():
    assert ChatConversation.__table__.c.conversation_id.unique is True


def test_chat_message_table_and_columns():
    assert ChatMessage.__tablename__ == "chat_messages"
    cols = {c.name for c in ChatMessage.__table__.columns}
    assert {"id", "user_id", "conversation_id", "role", "content", "tokens_used"} <= cols
