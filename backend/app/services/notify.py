"""Outbound email on behalf of a user, sent through their connected Gmail plugin
(`gmail.send` scope). Gracefully no-ops (returns False) when Gmail isn't connected
or the send fails — callers treat email as a best-effort convenience."""

import base64
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import PluginConnection
from .plugins.oauth import access_token
from .plugins.registry import get_provider

log = logging.getLogger(__name__)


async def send_email(db: AsyncSession, user_id: str, to: str, subject: str, body: str) -> bool:
    """Send a plain-text email as `user_id` via their Gmail connection."""
    try:
        spec = get_provider("gmail")
    except KeyError:
        return False
    conn = await db.scalar(
        select(PluginConnection).where(
            PluginConnection.user_id == user_id, PluginConnection.provider == "gmail"
        )
    )
    if not conn:
        return False
    try:
        tok = await access_token(db, spec, conn)  # auto-refreshes + persists
        raw = (
            f"To: {to}\r\nSubject: {subject}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        )
        b64 = base64.urlsafe_b64encode(raw.encode()).decode()
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.post(
                f"{spec.api_base}/users/me/messages/send",
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json={"raw": b64},
            )
        if r.status_code in (200, 202):
            return True
        log.warning("gmail send failed (%s): %s", r.status_code, r.text[:160])
    except Exception as e:
        log.warning("gmail send failed for user %s: %s", user_id, e)
    return False
