"""OAuth helpers: code exchange, token refresh, account-label lookup."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import PluginConnection
from .crypto import decrypt_token, encrypt_token
from .registry import ProviderSpec, callback_url

log = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=20.0)


async def exchange_code(spec: ProviderSpec, code: str) -> dict:
    """Swap an authorization code for tokens at the provider's token endpoint."""
    resp = await _http.post(
        spec.token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(spec.key),
            "client_id": spec.client_id,
            "client_secret": spec.client_secret,
        },
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("access_token"):
        raise ValueError(f"no access_token in provider response: {str(data)[:200]}")
    return data


async def fetch_account_label(spec: ProviderSpec, access_token: str) -> str | None:
    """Best-effort human label for the connected account (email / login)."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        if spec.key == "gmail":
            r = await _http.get(f"{spec.api_base}/users/me/profile", headers=headers)
            return r.json().get("emailAddress") if r.status_code == 200 else None
        if spec.key == "google_calendar":
            r = await _http.get(f"{spec.api_base}/users/me/calendarList/primary", headers=headers)
            return r.json().get("id") if r.status_code == 200 else None
        if spec.key == "github":
            r = await _http.get(f"{spec.api_base}/user", headers=headers)
            return r.json().get("login") if r.status_code == 200 else None
    except Exception as e:
        log.warning("account label fetch failed for %s: %s", spec.key, e)
    return None


def _aware(dt: datetime) -> datetime:
    """SQLAlchemy may hand back a naive datetime — treat it as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def access_token(db: AsyncSession, spec: ProviderSpec, conn: PluginConnection) -> str:
    """A valid access token for a stored connection, refreshing first if expired."""
    if conn.expires_at and _aware(conn.expires_at) > datetime.now(timezone.utc) + timedelta(minutes=1):
        return decrypt_token(conn.access_token_enc)
    if not conn.refresh_token_enc:
        return decrypt_token(conn.access_token_enc)  # non-expiring token (GitHub) or nothing we can do
    resp = await _http.post(
        spec.token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": decrypt_token(conn.refresh_token_enc),
            "client_id": spec.client_id,
            "client_secret": spec.client_secret,
        },
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    new_access = data.get("access_token")
    if not new_access:
        raise ValueError(f"token refresh failed: {str(data)[:200]}")
    conn.access_token_enc = encrypt_token(new_access)
    if data.get("refresh_token"):
        conn.refresh_token_enc = encrypt_token(data["refresh_token"])
    conn.expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
        if data.get("expires_in")
        else None
    )
    await db.commit()
    return new_access
