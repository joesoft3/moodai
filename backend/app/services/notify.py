"""Push notifications via Firebase Cloud Messaging HTTP v1 (Phase 1).

No extra client SDK: we mint an OAuth2 access token by self-signing a JWT (RS256)
with the service account's private key, then POST to the FCM v1 send endpoint.
Every entry point no-ops cleanly when FCM_PROJECT_ID / FCM_SERVICE_ACCOUNT_JSON
aren't configured — push can never break chat, arena or plugin flows.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import delete, select

from ..config import settings
from ..db.models import Device, UsageEvent
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_SEND = "https://fcm.googleapis.com/v1/projects/{pid}/messages:send"
_DEAD = {"unregistered", "UNREGISTERED", "NOT_FOUND", "INVALID_ARGUMENT"}

_token_cache: dict[str, object] = {"token": "", "exp": 0.0}
_last_sent: dict[tuple[str, str], float] = {}


def enabled() -> bool:
    return bool(settings.FCM_PROJECT_ID and settings.FCM_SERVICE_ACCOUNT_JSON)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def service_account() -> dict:
    try:
        return json.loads(settings.FCM_SERVICE_ACCOUNT_JSON)
    except Exception:
        log.warning("FCM_SERVICE_ACCOUNT_JSON is not valid JSON — push disabled")
        return {}


def build_jwt_claims(sa: dict, now: int | None = None) -> dict:
    """Claims for the OAuth2 JWT-bearer grant (pure — unit tested)."""
    now = now or int(time.time())
    return {
        "iss": sa.get("client_email", ""),
        "sub": sa.get("client_email", ""),
        "aud": TOKEN_URL,
        "scope": FCM_SCOPE,
        "iat": now,
        "exp": now + 3000,
    }


def _signed_jwt(sa: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    claims = build_jwt_claims(sa)
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


async def _oauth_token() -> str:
    now = time.time()
    cached = str(_token_cache["token"])
    if cached and float(_token_cache["exp"]) > now + 60:
        return cached
    sa = service_account()
    if not sa:
        return ""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": _signed_jwt(sa),
            },
        )
        r.raise_for_status()
        data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["exp"] = now + float(data.get("expires_in", 3600))
    return str(_token_cache["token"])


def build_message(token: str, title: str, body: str, data: dict | None = None) -> dict:
    """FCM v1 message envelope (pure — unit tested). Data values must be strings."""
    msg: dict = {"notification": {"title": title, "body": body}}
    if data:
        msg["data"] = {k: str(v) for k, v in data.items()}
    return {"message": {"token": token, **msg}}


async def _send_one(access: str, token: str, title: str, body: str, data: dict | None) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            _FCM_SEND.format(pid=settings.FCM_PROJECT_ID),
            headers={"Authorization": f"Bearer {access}"},
            json=build_message(token, title, body, data),
        )
    if r.status_code in (404, 410):
        return False, "UNREGISTERED"
    if r.status_code >= 400:
        code = f"http_{r.status_code}"
        try:
            for detail in r.json().get("error", {}).get("details", []):
                if detail.get("errorCode"):
                    code = detail["errorCode"]
                    break
        except Exception:
            pass
        return False, code
    return True, "ok"


def _cooled(user_id: str, kind: str) -> bool:
    """Process-local cooldown: one push per user+kind per NOTIFY_COOLDOWN_SECONDS."""
    last = _last_sent.get((user_id, kind), 0.0)
    return (time.time() - last) < settings.NOTIFY_COOLDOWN_SECONDS


async def notify_user(user_id: str, kind: str, title: str, body: str, data: dict | None = None) -> int:
    """Fan a notification out to every registered device of the user. Returns devices reached.

    Analytics v3: each send attempt lands in usage_events as `push_attempt:{kind}`
    / `push:{kind}` (delivered) / `push_prune` — the owner funnel lives on those."""
    if not enabled() or _cooled(user_id, kind):
        return 0
    _last_sent[(user_id, kind)] = time.time()  # stamp first so a failure can't spam
    try:
        access = await _oauth_token()
        if not access:
            return 0
        sent = 0
        async with SessionLocal() as s:
            tokens = (
                await s.execute(select(Device.token).where(Device.user_id == user_id))
            ).scalars().all()
            if tokens:
                s.add(UsageEvent(user_id=user_id, kind=f"push_attempt:{kind}", model="fcm"))
            pruned = 0
            for tok in tokens:
                ok, why = await _send_one(access, tok, title, body, data)
                if ok:
                    sent += 1
                elif why in _DEAD:  # prune dead tokens so the table stays lean
                    pruned += 1
                    await s.execute(delete(Device).where(Device.token == tok))
            for _ in range(sent):
                s.add(UsageEvent(user_id=user_id, kind=f"push:{kind}", model="fcm"))
            for _ in range(pruned):
                s.add(UsageEvent(user_id=user_id, kind="push_prune", model="fcm"))
            await s.commit()
        return sent
    except Exception as e:  # noqa: BLE001 — push must never take the main flow down
        log.warning("push notify failed (%s): %s", kind, e)
        return 0


def push_later(user_id: str, kind: str, title: str, body: str, data: dict | None = None) -> None:
    """Fire-and-forget wrapper safe to call from inside a running event loop."""
    try:
        asyncio.get_running_loop().create_task(notify_user(user_id, kind, title, body, data))
    except RuntimeError:
        pass


def notify_approval_needed(user_id: str, action_name: str) -> None:
    pretty = action_name.replace("gmail_", "").replace("google_calendar_", "").replace("_", " ")
    push_later(
        user_id, "approval", "✋ Approval needed",
        f"Mood wants to {pretty} — approve or reject in the ✋ inbox",
        {"kind": "approval", "screen": "/plugins"},
    )


def notify_arena_done(user_id: str, winner: str | None) -> None:
    tail = f" — {winner} takes it" if winner else ""
    push_later(
        user_id, "arena", "⚔️ Arena verdict in",
        f"Your debate just finished{tail}.",
        {"kind": "arena"},
    )


# --------------------------------------------------------------------- team-invite email
async def send_email(db: "AsyncSession", user_id: str, to: str, subject: str, body: str) -> bool:
    """Send plain-text email as `user_id` via their connected Gmail plugin.

    Best-effort convenience for workspace invites: gracefully returns False when
    Gmail isn't connected or the send fails — callers report `failed` recipients.
    (Restored after the Phase-1 FCM rewrite dropped it while workspaces.py still
    depended on it — caught by the app-boot import smoke test.)"""
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (type-checking)
    from sqlalchemy import select as sa_select

    from ..db.models import PluginConnection
    from .plugins.oauth import access_token
    from .plugins.registry import get_provider

    try:
        spec = get_provider("gmail")
    except KeyError:
        return False
    conn = await db.scalar(
        sa_select(PluginConnection).where(
            PluginConnection.user_id == user_id, PluginConnection.provider == "gmail"
        )
    )
    if not conn:
        return False
    try:
        tok = await access_token(db, spec, conn)  # auto-refreshes + persists
        raw = f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
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
