from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Conversation, User
from ...db.session import get_db
from ...services.memory import clear_memories, delete_memory, list_memories
from ..deps import get_current_user

router = APIRouter()


@router.get("")
async def get_memories(user: User = Depends(get_current_user)):
    try:
        return {"memories": await list_memories(user.id)}
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Memory store unavailable")


@router.delete("/{memory_id}")
async def remove_memory(memory_id: str, user: User = Depends(get_current_user)):
    ok = await delete_memory(user.id, memory_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    return {"deleted": True}


@router.delete("")
async def wipe_memories(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Forget everything: facts + past-chat recall vectors (Qdrant) and summaries (Postgres)."""
    await clear_memories(user.id)
    await db.execute(
        update(Conversation).where(Conversation.user_id == user.id).values(summary=None)
    )
    await db.commit()
    return {"cleared": True}
