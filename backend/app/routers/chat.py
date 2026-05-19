"""Chat router — AskMe conversational interface."""
import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
    ChatSessionListItem,
)
from app.auth.jwt_handler import get_current_user
from app.services.chat_service import process_chat

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def send_message(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a chat message and get AI response."""
    content = payload.message.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(content) > 10000:
        raise HTTPException(status_code=400, detail="Message too long (max 10000 characters)")

    session, assistant_msg = await process_chat(
        db=db,
        session_id=payload.session_id,
        message=content,
        user_id=user.id,
        user_email=user.email,
        context_alert_id=payload.context_alert_id,
        approve_tool_plan=payload.approve_tool_plan,
        tool_plan_id=payload.tool_plan_id,
        auto_investigate=payload.auto_investigate,
    )
    await db.commit()

    # Extract tool_plan from metadata if the AI wants user approval
    tool_plan = (assistant_msg.metadata_json or {}).get("tool_plan")

    return ChatResponse(
        session_id=session.id,
        message=assistant_msg.content,
        metadata_json=assistant_msg.metadata_json,
        tool_plan=tool_plan,
    )


@router.get("/sessions", response_model=List[ChatSessionListItem])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the current user's chat sessions."""
    result = await db.execute(
        select(
            ChatSession,
            func.count(ChatMessage.id).label("msg_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    rows = result.all()
    return [
        ChatSessionListItem(
            id=session.id,
            title=session.title,
            ai_mode=session.ai_mode,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=msg_count,
        )
        for session, msg_count in rows
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a chat session with all messages."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a chat session and all its messages."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    await db.delete(session)
    await db.flush()
    await db.commit()
