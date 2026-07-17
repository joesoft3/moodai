"""Plugin management: list/connect/disconnect OAuth apps (Gmail, Calendar, GitHub)."""

import logging
import urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import PendingAction, PluginConnection, User
from ...db.session import get_db
from ...services.plugins.crypto import encrypt_token
from ...services.plugins.oauth import exchange_code, fetch_account_label
from ...services.plugins.registry import PROVIDERS, callback_url, get_provider
from ...services.plugins.tools import PluginError, execute_tool
from ..deps import get_current_user

router = APIRouter()
log = logging.getLogger(__name__)


def _state_token(user_id: str, provider: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "scope": "plugin_oauth",
            "provider": provider,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALG,
    )


def _decode_state(state: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        if payload.get("scope") != "plugin_oauth":
            raise JWTError("wrong scope")
        return payload["sub"], payload["provider"]
    except JWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state — try connecting again")


@router.get("")
async def list_plugins(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(select(PluginConnection).where(PluginConnection.user_id == user.id))
    ).scalars().all()
    by_provider = {c.provider: c for c in rows}
    out = []
    for key, spec in PROVIDERS.items():
        conn = by_provider.get(key)
        out.append(
            {
                "provider": key,
                "name": spec.name,
                "icon": spec.icon,
                "description": spec.description,
                "configured": spec.configured,  # OAuth client id/secret present server-side
                "connected": conn is not None,
                "account": conn.account if conn else None,
                "connected_at": conn.created_at.isoformat() if conn and conn.created_at else None,
            }
        )
    return {"plugins": out}


@router.get("/{provider}/connect")
async def connect_plugin(provider: str, user: User = Depends(get_current_user)):
    spec = get_provider(provider)
    if not spec.configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{spec.name} OAuth not configured — set {('GOOGLE' if spec.key != 'github' else 'GITHUB')}_CLIENT_ID/SECRET",
        )
    params = {
        "client_id": spec.client_id,
        "redirect_uri": callback_url(spec.key),
        "response_type": "code",
        "scope": spec.scopes,
        "state": _state_token(user.id, spec.key),
        **spec.extra_auth_params,
    }
    return {"authorize_url": f"{spec.auth_url}?{urllib.parse.urlencode(params)}"}


@router.get("/{provider}/callback")
async def plugin_callback(
    provider: str,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    settings_url = f"{settings.FRONTEND_URL.rstrip('/')}/settings"
    if error or not code or not state:
        return RedirectResponse(f"{settings_url}?plugin=error")
    user_id, state_provider = _decode_state(state)
    spec = get_provider(provider)
    if state_provider != provider:
        return RedirectResponse(f"{settings_url}?plugin=error")
    try:
        tokens = await exchange_code(spec, code)
    except Exception as e:
        log.warning("plugin token exchange failed (%s): %s", provider, e)
        return RedirectResponse(f"{settings_url}?plugin=error")

    access = tokens["access_token"]
    account = await fetch_account_label(spec, access)
    conn = await db.scalar(
        select(PluginConnection).where(
            PluginConnection.user_id == user_id, PluginConnection.provider == provider
        )
    )
    if not conn:
        conn = PluginConnection(user_id=user_id, provider=provider)
        db.add(conn)
    conn.account = account
    conn.access_token_enc = encrypt_token(access)
    if tokens.get("refresh_token"):
        conn.refresh_token_enc = encrypt_token(tokens["refresh_token"])
    conn.scopes = tokens.get("scope", spec.scopes)[:500]
    conn.expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(tokens["expires_in"]))
        if tokens.get("expires_in")
        else None
    )
    await db.commit()
    return RedirectResponse(f"{settings_url}?plugin=connected")


@router.delete("/{provider}")
async def disconnect_plugin(
    provider: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    get_provider(provider)  # 404 on unknown
    await db.execute(
        delete(PluginConnection).where(
            PluginConnection.user_id == user.id, PluginConnection.provider == provider
        )
    )
    await db.commit()
    return {"disconnected": provider}


# ---------------- human-in-the-loop: approve / reject staged write actions ----------------


async def _owned_action(db: AsyncSession, user: User, action_id: str) -> PendingAction:
    action = await db.get(PendingAction, action_id)
    if not action or action.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    if action.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Action already {action.status}")
    return action


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Execute a staged write action and record its result."""
    action = await _owned_action(db, user, action_id)
    try:
        result = await execute_tool(db, user.id, action.tool, action.args or {})
        action.status = "approved"
        action.result = result
    except PluginError as e:
        action.status = "failed"
        action.result = {"error": str(e)}
    await db.commit()
    return {"status": action.status, "result": action.result}


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    action = await _owned_action(db, user, action_id)
    action.status = "rejected"
    await db.commit()
    return {"status": "rejected"}
