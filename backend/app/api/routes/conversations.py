import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Conversation, Message, SharedLink, User
from ...db.session import get_db
from ...schemas import ConversationCreate, RenameRequest
from ...services.recall import delete_chat_memory
from ..deps import get_current_user

router = APIRouter()


def conv_out(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def msg_out(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "user_id": m.user_id,  # author (team chats)
        "meta": m.meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("")
async def list_conversations(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    return [conv_out(c) for c in rows]


@router.post("", status_code=201)
async def create_conversation(
    req: ConversationCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = Conversation(user_id=user.id, title=(req.title or "New chat")[:200])
    db.add(conv)
    await db.commit()
    return conv_out(conv)


async def _get_owned(db: AsyncSession, user: User, cid: str) -> Conversation:
    conv = await db.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


async def _can_read(db: AsyncSession, user: User, cid: str) -> Conversation:
    """Owner, or any member when the conversation is shared in a workspace."""
    conv = await db.get(Conversation, cid)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if conv.user_id == user.id:
        return conv
    if conv.workspace_id:
        from .workspaces import membership_of

        if await membership_of(db, conv.workspace_id, user.id):
            return conv
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.get("/{cid}")
async def get_conversation(cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    conv = await _can_read(db, user, cid)
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
        )
    ).scalars().all()
    # author label map for team conversations (user messages carry user_id)
    authors: dict[str, str] = {}
    if conv.workspace_id:
        for uid_ in {m.user_id for m in rows if m.user_id}:
            u = await db.get(User, uid_)
            if u:
                authors[uid_] = u.display_name or u.email.split("@")[0]
    return {**conv_out(conv), "workspace_id": conv.workspace_id, "authors": authors, "messages": [msg_out(m) for m in rows]}


@router.patch("/{cid}")
async def rename_conversation(
    cid: str, req: RenameRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = await _get_owned(db, user, cid)
    conv.title = req.title[:200]
    await db.commit()
    return conv_out(conv)


@router.delete("/{cid}", status_code=204)
async def delete_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = await _get_owned(db, user, cid)
    await db.delete(conv)
    await db.commit()
    await delete_chat_memory(user.id, cid)  # forget this chat everywhere (best-effort)
    return Response(status_code=204)


@router.post("/{cid}/share", status_code=201)
async def share_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Create (or return the existing) public read-only link for a conversation."""
    conv = await _get_owned(db, user, cid)
    link = await db.scalar(select(SharedLink).where(SharedLink.conversation_id == conv.id))
    if not link:
        link = SharedLink(token=secrets.token_urlsafe(12), conversation_id=conv.id, user_id=user.id)
        db.add(link)
        await db.commit()
    return {"token": link.token, "path": f"/shared/{link.token}"}


@router.delete("/{cid}/share")
async def unshare_conversation(
    cid: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    conv = await _get_owned(db, user, cid)
    link = await db.scalar(select(SharedLink).where(SharedLink.conversation_id == conv.id))
    if link:
        await db.delete(link)
        await db.commit()
    return {"revoked": True}
