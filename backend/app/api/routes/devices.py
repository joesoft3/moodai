"""Device push-token registration (Phase 1 push — docs/PUSH-NOTIFICATIONS.md).

POST /devices            {token, platform}  → upsert; a token moving to another user
                                             (logout→login elsewhere) is re-pointed.
DELETE /devices/{token}                     → unregister (logout / disable).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Device, User
from ...db.session import get_db
from ..deps import get_current_user

router = APIRouter()


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios|web)$")


@router.post("", status_code=201)
async def register_device(
    req: DeviceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    existing = (
        await db.execute(select(Device).where(Device.token == req.token))
    ).scalar_one_or_none()
    if existing:
        existing.user_id = user.id
        existing.platform = req.platform
        existing.last_seen_at = datetime.now(timezone.utc)
    else:
        db.add(Device(user_id=user.id, token=req.token, platform=req.platform))
    await db.commit()
    return {"ok": True}


@router.delete("/{token}")
async def unregister_device(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await db.execute(delete(Device).where(Device.token == token, Device.user_id == user.id))
    await db.commit()
    return {"ok": True}
