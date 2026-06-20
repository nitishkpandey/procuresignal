"""Chat request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    title: Optional[str] = None
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ConversationListResponse(BaseModel):
    user_id: str
    conversations: list[ConversationResponse]
    total_count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    tokens_used: Optional[int] = None
    created_at: Optional[datetime] = None


class MessageListResponse(BaseModel):
    conversation_id: str
    messages: list[MessageResponse]
    total_count: int
