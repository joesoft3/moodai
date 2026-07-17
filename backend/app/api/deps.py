import redis.asyncio as redis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.security import decode_token
from ..db.models import User
from ..db.session import get_db

bearer = HTTPBearer()


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_token(creds.credentials)
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def is_effective_admin(user: User) -> bool:
    """DB flag OR owner email listed in ADMIN_EMAILS env."""
    return bool(user.is_admin or user.email.lower() in settings.admin_email_set)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_effective_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def enforce_rate_limit(bucket: str, per_minute: int) -> None:
    """Simple per-user token bucket. Fails open if Redis is unavailable."""
    try:
        r = await get_redis()
        key = f"rl:{bucket}"
        async with r.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, 60)
            count, _ = await pipe.execute()
        if int(count) > per_minute:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded — slow down.")
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open
