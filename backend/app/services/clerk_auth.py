"""Clerk federation (Phase 1): verify Clerk session JWTs, resolve the user's
email, and hand the account lifecycle to our auth (find-or-provision by email).

Design decisions (see docs/CLERK-AUTH-ASSESSMENT.md):
- Zero schema changes — the link key is the email address; the Clerk `sub`
  is re-verified on every login (stateless).
- Provisioning respects the same signup gates as /auth/register.
- Clerk-provisioned users get an unguessable random password hash; they can
  set a real password later if a change-password flow ships.
"""

import logging
import time

import httpx
from jose import jwk, jwt
from jose.exceptions import JWTError

from ..config import settings

log = logging.getLogger(__name__)

_jwks_cache: dict = {"keys": [], "fetched_at": 0}
JWKS_TTL = 6 * 3600


def clerk_enabled() -> bool:
    return bool((settings.CLERK_ISSUER or "").strip())


def _jwks_url() -> str:
    return (settings.CLERK_JWKS_URL or "").strip() or (
        f"{settings.CLERK_ISSUER.rstrip('/')}/.well-known/jwks.json"
    )


async def _fetch_jwks(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < JWKS_TTL:
        return _jwks_cache["keys"]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(_jwks_url())
        r.raise_for_status()
        keys = r.json().get("keys", [])
    _jwks_cache.update({"keys": keys, "fetched_at": now})
    return keys


class ClerkTokenError(Exception):
    pass


async def verify_clerk_token(token: str) -> dict:
    """RS256/JWKS verification with issuer + optional audience checks."""
    if not clerk_enabled():
        raise ClerkTokenError("Clerk federation is not configured")
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise ClerkTokenError(f"malformed token: {e}") from e
    kid = header.get("kid")
    keys = await _fetch_jwks()
    match = next((k for k in keys if k.get("kid") == kid), None)
    if match is None:  # key rotation: one forced refresh, then give up
        match = next((k for k in await _fetch_jwks(force=True) if k.get("kid") == kid), None)
    if match is None:
        raise ClerkTokenError("unknown signing key (kid)")
    try:
        key = jwk.construct(match, algorithm="RS256")
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.CLERK_ISSUER,
            audience=settings.CLERK_AUDIENCE or None,
            options={"verify_aud": bool(settings.CLERK_AUDIENCE)},
        )
    except JWTError as e:
        raise ClerkTokenError(f"token verification failed: {e}") from e


async def fetch_primary_email(sub: str) -> str | None:
    """Clerk session tokens don't necessarily carry email — look it up via the
    Backend API when the claim is absent."""
    if not settings.CLERK_SECRET_KEY:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://api.clerk.com/v1/users/{sub}",
            headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
        )
        if r.status_code != 200:
            log.warning("clerk profile fetch failed (%s)", r.status_code)
            return None
        data = r.json()
    primary_id = data.get("primary_email_address_id")
    emails = data.get("email_addresses") or []
    for e in emails:
        if e.get("id") == primary_id and e.get("email_address"):
            return e["email_address"]
    return emails[0]["email_address"] if emails and emails[0].get("email_address") else None


async def resolve_email(claims: dict) -> str | None:
    """Email from token claims when present, else backend-API lookup."""
    for k in ("email", "email_address", "primary_email"):
        v = claims.get(k)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    sub = claims.get("sub")
    if sub:
        return await fetch_primary_email(sub)
    return None
