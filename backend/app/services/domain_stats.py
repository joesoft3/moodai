"""Per-custom-domain request analytics — Redis-backed, zero schema changes, fail-open.

Attribution: the frontend sends `X-Mood-Host: <page origin host>` on every API call
(the HTTP Host of the API itself is the platform's own host). Host → active Domain
lookups hit Postgres at most once per 5 minutes per host (Redis-cached, negative
results cached for 60s). Counters roll per UTC day with a 40-day TTL:

  domstat:{domain_id}:req:{yyyymmdd}  INCR   → requests
  domstat:{domain_id}:usr:{yyyymmdd}  SADD   → unique authenticated users
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis

from ..config import settings
from ..core.security import decode_token

log = logging.getLogger(__name__)

HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
TTL_SECONDS = 40 * 86400

_redis: redis.Redis | None = None


async def _r() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def clean_host(raw: str) -> str:
    h = (raw or "").split(":")[0].strip().lower().rstrip(".")
    return h if HOST_RE.match(h) else ""


def _is_platform_host(host: str) -> bool:
    if host in ("localhost",) or host.startswith("127.") or host.endswith(".localhost"):
        return True
    if settings.BASE_DOMAIN and clean_host(settings.BASE_DOMAIN) == host:
        return True
    if settings.PLATFORM_CNAME_TARGET and settings.PLATFORM_CNAME_TARGET.rstrip(".").lower() == host:
        return True
    return False


async def _resolve_domain_id(host: str) -> str | None:
    """host → active Domain.id (Redis-cached; '-' marks 'not a custom domain')."""
    r = await _r()
    cached = await r.get(f"domcache:{host}")
    if cached is not None:
        return None if cached == "-" else cached
    from sqlalchemy import select

    from ..db.models import Domain
    from ..db.session import SessionLocal

    domain_id = "-"
    try:
        async with SessionLocal() as s:
            d = await s.scalar(select(Domain).where(Domain.domain == host, Domain.status == "active"))
            if d:
                domain_id = d.id
    except Exception as e:
        log.warning("domain resolve failed for %s: %s", host, e)
        return None  # don't cache DB failures
    try:
        await r.set(f"domcache:{host}", domain_id, ex=300 if domain_id != "-" else 60)
    except Exception:
        pass
    return None if domain_id == "-" else domain_id


async def record_request(host_raw: str, auth_header: str) -> None:
    """Fire-and-forget counter bump for one API request. NEVER raises."""
    try:
        host = clean_host(host_raw)
        if not host or _is_platform_host(host):
            return
        domain_id = await _resolve_domain_id(host)
        if not domain_id:
            return
        user_id = None
        if auth_header.startswith("Bearer "):
            try:
                user_id = decode_token(auth_header[7:]).get("sub")
            except Exception:
                user_id = None
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        r = await _r()
        async with r.pipeline(transaction=False) as pipe:
            pipe.incr(f"domstat:{domain_id}:req:{day}")
            pipe.expire(f"domstat:{domain_id}:req:{day}", TTL_SECONDS)
            if user_id:
                pipe.sadd(f"domstat:{domain_id}:usr:{day}", user_id)
                pipe.expire(f"domstat:{domain_id}:usr:{day}", TTL_SECONDS)
            await pipe.execute()
    except Exception:
        pass  # analytics must never break requests


async def analytics(domain_id: str, days: int = 14) -> dict:
    """Daily request/unique-user series + totals for the domain dashboard."""
    now = datetime.now(timezone.utc)
    day_keys = [(now - timedelta(days=i)).date() for i in range(days - 1, -1, -1)]
    series = [{"day": d.isoformat(), "requests": 0, "users": 0} for d in day_keys]
    try:
        r = await _r()
        async with r.pipeline(transaction=False) as pipe:
            for d in day_keys:
                pipe.get(f"domstat:{domain_id}:req:{d.strftime('%Y%m%d')}")
            for d in day_keys:
                pipe.scard(f"domstat:{domain_id}:usr:{d.strftime('%Y%m%d')}")
            out = await pipe.execute()
        for i, d in enumerate(day_keys):
            series[i]["requests"] = int(out[i] or 0)
            series[i]["users"] = int(out[days + i] or 0)
    except Exception as e:
        log.warning("domain analytics read failed: %s", e)
    total_req = sum(p["requests"] for p in series)
    # unique users across the window calls for a union; SCARD of SUNIONSTORE would
    # mutate state, so approximate with the max daily unique (documented in UI).
    return {
        "days": series,
        "today": series[-1],
        "total_requests": total_req,
        "peak_daily_users": max((p["users"] for p in series), default=0),
    }
