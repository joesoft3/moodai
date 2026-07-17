"""App owner panel: platform stats, the app access gate (open signup + app password),
and user administration (plans, password resets, admin grants, deletes)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.security import hash_password
from ...db.models import Conversation, Domain, Message, UsageEvent, User, Workspace
from ...db.session import get_db
from ...schemas import AdminFlagUpdate, AdminPasswordReset, AdminPlanUpdate, AdminSettingsUpdate
from ...services.platform_settings import (
    KEY_APP_PASSWORD,
    KEY_SIGNUP_OPEN,
    get_setting,
    set_setting,
)
from ..deps import require_admin

router = APIRouter()


def _user_out(u: User, conv_count: int = 0, tokens_month: int = 0) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "plan": u.plan,
        "is_admin": u.is_admin,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "conversations": conv_count,
        "tokens_month": tokens_month,
    }


@router.get("/overview")
async def admin_overview(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Platform snapshot for the owner dashboard."""
    async def count(model) -> int:
        return int((await db.scalar(select(func.count(model.id)))) or 0)

    month_start = (await db.execute(select(func.date_trunc("month", func.now())))).scalar()
    tokens_month = int(
        (await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0)).where(
                UsageEvent.created_at >= month_start
            )
        ))
        or 0
    )
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    active_week = int(
        (await db.scalar(select(func.count(func.distinct(UsageEvent.user_id))).where(UsageEvent.created_at >= week_ago)))
        or 0
    )
    recent = (
        await db.execute(select(User).order_by(User.created_at.desc()).limit(6))
    ).scalars().all()
    return {
        "stats": {
            "users": await count(User),
            "conversations": await count(Conversation),
            "messages": await count(Message),
            "workspaces": await count(Workspace),
            "domains_active": int(
                (await db.scalar(select(func.count(Domain.id)).where(Domain.status == "active"))) or 0
            ),
            "tokens_month": tokens_month,
            "active_users_week": active_week,
        },
        "recent_users": [_user_out(u) for u in recent],
        "capabilities": {
            "stripe": bool(settings.STRIPE_SECRET_KEY),
            "registrar": bool(settings.GODADDY_API_KEY and settings.GODADDY_API_SECRET),
            "registrar_env": settings.GODADDY_ENV,
            "voice": bool(settings.OPENAI_API_KEY),
            "plugins": bool(settings.PLUGIN_TOKEN_KEY or settings.JWT_SECRET),
            "platform_cname": bool(settings.PLATFORM_CNAME_TARGET),
        },
    }


# --------------------------------------------------------------------- app access gate
@router.get("/settings")
async def admin_get_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    gate = await get_setting(db, KEY_APP_PASSWORD, {})
    su = await get_setting(db, KEY_SIGNUP_OPEN, {"open": True})
    return {
        "signup_open": bool(su.get("open", True)),
        "app_password_set": bool(gate.get("hash")),
        "admin_emails": sorted(settings.admin_email_set),
    }


@router.put("/settings")
async def admin_put_settings(
    req: AdminSettingsUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    """Rotate/clear the **app access password** and toggle open signups."""
    if req.signup_open is not None:
        await set_setting(db, KEY_SIGNUP_OPEN, {"open": req.signup_open})
    if req.app_password is not None:
        pw = req.app_password.strip()
        if pw == "":
            await set_setting(db, KEY_APP_PASSWORD, {})  # cleared — open signup (subject to toggle)
        else:
            if len(pw) < 8:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "App password must be 8+ characters")
            await set_setting(db, KEY_APP_PASSWORD, {"hash": hash_password(pw), "set_by": admin.email})
    return await admin_get_settings(db, admin)


# --------------------------------------------------------------------- user administration
@router.get("/users")
async def admin_users(
    q: str | None = Query(default=None, max_length=120),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    stmt = select(User).order_by(User.created_at.desc()).limit(50)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = (
            select(User)
            .where(or_(func.lower(User.email).like(like), func.lower(func.coalesce(User.display_name, "")).like(like)))
            .order_by(User.created_at.desc())
            .limit(50)
        )
    rows = (await db.execute(stmt)).scalars().all()
    month_start = (await db.execute(select(func.date_trunc("month", func.now())))).scalar()
    out = []
    for u in rows:
        convs = int((await db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == u.id))) or 0)
        toks = int(
            (await db.scalar(
                select(func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0)).where(
                    UsageEvent.user_id == u.id, UsageEvent.created_at >= month_start
                )
            ))
            or 0
        )
        out.append(_user_out(u, convs, toks))
    return {"users": out}


async def _target_user(db: AsyncSession, uid: str) -> User:
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


@router.post("/users/{uid}/plan")
async def admin_set_plan(
    uid: str, req: AdminPlanUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    u = await _target_user(db, uid)
    u.plan = req.plan
    await db.commit()
    return {"id": u.id, "plan": u.plan}


@router.post("/users/{uid}/password")
async def admin_reset_password(
    uid: str, req: AdminPasswordReset, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    """Owner resets ANY user's password (including another admin's)."""
    u = await _target_user(db, uid)
    u.hashed_password = hash_password(req.password)
    await db.commit()
    return {"reset": u.email}


@router.post("/users/{uid}/admin")
async def admin_toggle_admin(
    uid: str, req: AdminFlagUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    u = await _target_user(db, uid)
    if u.id == admin.id and not req.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't revoke your own admin rights")
    u.is_admin = req.is_admin
    await db.commit()
    return {"id": u.id, "is_admin": u.is_admin}


@router.delete("/users/{uid}")
async def admin_delete_user(uid: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    u = await _target_user(db, uid)
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't delete your own account here")
    if u.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Revoke admin rights first, then delete")
    await db.delete(u)  # conversations/messages cascade via FK
    await db.commit()
    return {"deleted": u.email}
