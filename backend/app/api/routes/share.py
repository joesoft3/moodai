"""Public, unauthenticated read of shared conversations (revocable via the
conversation owner deleting the link or the conversation)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Conversation, Message, SharedLink
from ...db.session import get_db
from ..deps import enforce_rate_limit

router = APIRouter()


@router.get("/{token}")
async def get_shared(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "anon"
    await enforce_rate_limit(f"share:{ip}", 60)
    link = await db.scalar(select(SharedLink).where(SharedLink.token == token))
    if not link:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This shared link is invalid or has been revoked")
    conv = await db.get(Conversation, link.conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation no longer exists")
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    msgs = [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in rows
        if m.role in ("user", "assistant")
    ][:200]
    return {
        "title": conv.title,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "messages": msgs,
    }
