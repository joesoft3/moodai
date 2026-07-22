"""💓 DB keep-warm — pin the serverless Postgres (Neon) compute awake.

Live forensics that motivated this: after ~5 minutes idle, the first DB touch paid a
4-15s "wake-up" (Neon suspends/lazily resumes the compute), which then cascaded into
context-budget timeouts and memory-blind first messages. The Fly machines are always
on, so an in-process SELECT 1 heartbeat from THIS process keeps the shared Neon
endpoint hot for every host (the Vercel API points at the same compute endpoint —
one warm endpoint warms both APIs).

Cost honesty: the heartbeat itself is a trivial 50ms query; what it prevents is the
SUSPEND, so the compute simply stays running (see DB_KEEP_WARM_S to tune, or
DB_KEEP_WARM=false to allow idle suspension).
"""

import asyncio
import logging
from datetime import datetime, timezone

import sqlalchemy as sa

from ..config import settings
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_pings: int = 0
_last_ping: str | None = None


def keep_warm_enabled() -> bool:
    return bool(settings.DB_KEEP_WARM)


def keep_warm_status() -> dict:
    """Surfaced on /healthz so the heartbeat is verifiable without log access."""
    return {
        "enabled": keep_warm_enabled(),
        "running": _task is not None,
        "interval_s": settings.DB_KEEP_WARM_S,
        "pings": _pings,
        "last_ping": _last_ping,
    }


async def _loop() -> None:
    global _pings, _last_ping
    interval = max(30.0, float(settings.DB_KEEP_WARM_S))
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as db:
                await db.execute(sa.text("SELECT 1"))
            _pings += 1
            _last_ping = datetime.now(timezone.utc).isoformat()
            log.debug("db keep-warm ping ok")
        except Exception as e:  # never let a blip kill the heartbeat
            log.info("db keep-warm ping failed (retrying next cycle): %s", e)


def start_keep_warm() -> None:
    """Idempotent starter — called once from the app lifespan."""
    global _task
    if not keep_warm_enabled() or _task is not None:
        return
    _task = asyncio.create_task(_loop())
    log.info("💓 db keep-warm started (SELECT 1 every %ss)", settings.DB_KEEP_WARM_S)


async def stop_keep_warm() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
