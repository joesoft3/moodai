"""DB-backed platform settings owned by the app admin.

Used by the auth gate (signup_open / app password) and readable via the owner
panel. Values are small JSON documents; reads happen on low-traffic paths only.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PlatformSetting

KEY_SIGNUP_OPEN = "signup_open"        # {"open": bool}
KEY_APP_PASSWORD = "app_password_hash"  # {"hash": str}


async def get_setting(db: AsyncSession, key: str, default: dict | None = None) -> dict:
    row = await db.get(PlatformSetting, key)
    return dict(row.value) if row else dict(default or {})


async def set_setting(db: AsyncSession, key: str, value: dict) -> None:
    row = await db.get(PlatformSetting, key)
    if not row:
        row = PlatformSetting(key=key)
        db.add(row)
    row.value = value
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def signup_open(db: AsyncSession) -> bool:
    return bool((await get_setting(db, KEY_SIGNUP_OPEN, {"open": True})).get("open", True))


async def app_password_hash(db: AsyncSession) -> str | None:
    return (await get_setting(db, KEY_APP_PASSWORD, {})).get("hash") or None
