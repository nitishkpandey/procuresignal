"""Chat REST + WebSocket endpoints."""

import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from procuresignal.chat.chat_client import ChatLLMClient
from procuresignal.chat.context import build_system_prompt
from procuresignal.config import database
from procuresignal.models import ChatConversation, ChatMessage
from sqlalchemy import asc, delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas.chat import (
    ClearHistoryResponse,
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


@router.delete("/conversations", response_model=ClearHistoryResponse)
async def clear_conversation_history(
    user_id: str = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> ClearHistoryResponse:
    """Delete all chat conversations and messages for a user."""

    message_result = await session.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    conversation_result = await session.execute(
        delete(ChatConversation).where(ChatConversation.user_id == user_id)
    )
    await session.commit()
    return ClearHistoryResponse(
        user_id=user_id,
        deleted_conversations=conversation_result.rowcount or 0,
        deleted_messages=message_result.rowcount or 0,
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


def _build_chat_client() -> ChatLLMClient:
    """Factory for the streaming chat client (overridable in tests)."""

    return ChatLLMClient()


async def _ensure_conversation(session_maker, user_id: str, conversation_id: str) -> None:
    async with session_maker() as session:
        conversation = await _get_conversation(session, conversation_id)
        if conversation is None:
            session.add(
                ChatConversation(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title=None,
                    message_count=0,
                    last_message_at=None,
                )
            )
            await session.commit()


async def _persist_user_message(
    session_maker, user_id: str, conversation_id: str, text: str
) -> tuple[str, list[dict]]:
    """Persist the user message, set title if first, return (system_prompt, history)."""

    async with session_maker() as session:
        session.add(
            ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role="user",
                content=text,
                tokens_used=None,
            )
        )
        conversation = await _get_conversation(session, conversation_id)
        if conversation is not None and not conversation.title:
            conversation.title = text[:200]
        await session.commit()

        history_rows = (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(asc(ChatMessage.created_at), asc(ChatMessage.id))
            )
        ).all()
        history = [{"role": m.role, "content": m.content} for m in history_rows[:-1]]
        system_prompt = await build_system_prompt(session, user_id)
    return system_prompt, history


async def _persist_assistant_message(
    session_maker, user_id: str, conversation_id: str, text: str, tokens_used: int | None
) -> None:
    async with session_maker() as session:
        session.add(
            ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=text,
                tokens_used=tokens_used,
            )
        )
        conversation = await _get_conversation(session, conversation_id)
        if conversation is not None:
            conversation.message_count = (conversation.message_count or 0) + 2
            conversation.last_message_at = datetime.utcnow()
        await session.commit()


@router.websocket("/ws/chat/{user_id}/{conversation_id}")
async def chat_websocket(websocket: WebSocket, user_id: str, conversation_id: str) -> None:
    """Stream a context-aware chat response, persisting both sides of the exchange."""

    await websocket.accept()

    session_maker = (
        getattr(database.db_config, "session_maker", None) if database.db_config else None
    )
    if session_maker is None:
        await websocket.send_json({"type": "error", "content": "Database not initialized"})
        await websocket.close()
        return

    try:
        client = _build_chat_client()
    except ValueError:
        await websocket.send_json(
            {"type": "error", "content": "Chat is unavailable: OPENAI_API_KEY not configured"}
        )
        await websocket.close()
        return

    await _ensure_conversation(session_maker, user_id, conversation_id)

    try:
        while True:
            payload = await websocket.receive_json()
            user_message = (payload or {}).get("message")
            if not user_message:
                await websocket.send_json({"type": "error", "content": "Missing 'message' field"})
                continue

            try:
                system_prompt, history = await _persist_user_message(
                    session_maker, user_id, conversation_id, user_message
                )
                await websocket.send_json(
                    {"type": "start", "content": "Processing your message..."}
                )
                chunks: list[str] = []
                async for delta in client.stream_chat(system_prompt, history, user_message):
                    chunks.append(delta)
                    await websocket.send_json({"type": "stream", "content": delta})
                # Persist BEFORE "end" so the terminal frame guarantees the assistant
                # message is committed; a client that disconnects on "end" could
                # otherwise query history before the write lands (race → lost message).
                await _persist_assistant_message(
                    session_maker,
                    user_id,
                    conversation_id,
                    "".join(chunks),
                    getattr(client, "last_tokens_used", None),
                )
                await websocket.send_json({"type": "end", "content": "Response complete"})
            except Exception as exc:  # noqa: BLE001 — surface to client, keep socket open
                await websocket.send_json(
                    {"type": "error", "content": f"Failed to process message: {exc}"}
                )
    except WebSocketDisconnect:
        return
