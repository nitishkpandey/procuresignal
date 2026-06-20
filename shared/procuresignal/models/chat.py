"""Chat conversation and message models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ChatConversation(BaseModel):
    """A chat conversation thread for a user."""

    __tablename__ = "chat_conversations"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("idx_chat_conversations_user_last", "user_id", "last_message_at"),)


class ChatMessage(BaseModel):
    """A single message within a chat conversation."""

    __tablename__ = "chat_messages"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("idx_chat_messages_conv_created", "conversation_id", "created_at"),)
