"""Chat REST + WebSocket endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.models import ChatConversation, ChatMessage
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.chat import (
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api", tags=["chat"])


async def _get_conversation(session: AsyncSession, conversation_id: str) -> ChatConversation | None:
    return await session.scalar(
        select(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
    )


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    """Create a new, empty conversation and return its generated id."""

    conversation = ChatConversation(
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        title=None,
        message_count=0,
        last_message_at=None,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ConversationListResponse:
    """List a user's conversations, most recently active first."""

    rows = (
        await session.scalars(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(desc(ChatConversation.last_message_at), desc(ChatConversation.created_at))
        )
    ).all()
    return ConversationListResponse(
        user_id=user_id,
        conversations=[ConversationResponse.model_validate(r) for r in rows],
        total_count=len(rows),
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def get_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> MessageListResponse:
    """Return the ordered messages of a conversation."""

    conversation = await _get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    rows = (
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(asc(ChatMessage.created_at), asc(ChatMessage.id))
        )
    ).all()
    return MessageListResponse(
        conversation_id=conversation_id,
        messages=[MessageResponse.model_validate(r) for r in rows],
        total_count=len(rows),
    )
