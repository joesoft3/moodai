"""First-run bootstrap: guaranteed owner account + optional sign-up access gate.

Configured exclusively through `.env` (see `.env.example`):

  ADMIN_BOOTSTRAP_EMAIL      → email of the guaranteed owner account
  ADMIN_BOOTSTRAP_PASSWORD   → its password (owner-only — keep secret!)
  APP_PASSWORD               → optional sign-up access code seeded into the
                               platform gate (rotatable later from the owner panel)

Everything is idempotent and fail-open: it only creates/promotes/seeds, never
overwrites an owner-panel value or an existing password.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from ..config import settings
from ..core.security import hash_password
from ..db.models import User
from ..db.session import SessionLocal
from .platform_settings import KEY_APP_PASSWORD, get_setting, set_setting

log = logging.getLogger(__name__)


async def bootstrap_admin() -> None:
    """Create (or promote) the owner account from env credentials.

    - New email  → account created with the env password, `is_admin=True`.
    - Known email → only promoted to admin; the existing password is untouched.
    """
    email = (settings.ADMIN_BOOTSTRAP_EMAIL or "").strip().lower()
    password = settings.ADMIN_BOOTSTRAP_PASSWORD or ""
    if not email or not password:
        return
    try:
        async with SessionLocal() as db:
            res = await db.execute(select(User).where(User.email == email))
            user = res.scalar_one_or_none()
            if user is None:
                db.add(
                    User(
                        email=email,
                        hashed_password=hash_password(password),
                        display_name="Owner",
                        is_admin=True,
                    )
                )
                log.info("🔐 bootstrap: owner account created (%s)", email)
            elif not user.is_admin:
                user.is_admin = True
                log.info("🔐 bootstrap: existing account promoted to owner (%s)", email)
            await db.commit()
    except Exception as e:  # tables may not exist yet on a broken deploy — never crash boot
        log.warning("bootstrap_admin skipped: %s", e)


async def seed_app_password_from_env() -> None:
    """Seed the sign-up access code from APP_PASSWORD once; the owner panel wins after that."""
    if not (settings.APP_PASSWORD or ""):
        return
    try:
        async with SessionLocal() as db:
            current = await get_setting(db, KEY_APP_PASSWORD, {})
            if current.get("hash"):
                return  # already set (env seed or owner panel) — never overwrite
            await set_setting(
                db,
                KEY_APP_PASSWORD,
                {"hash": hash_password(settings.APP_PASSWORD), "set_by": "env"},
            )
            log.info("🔐 bootstrap: sign-up access code seeded from APP_PASSWORD env")
    except Exception as e:
        log.warning("seed_app_password_from_env skipped: %s", e)
