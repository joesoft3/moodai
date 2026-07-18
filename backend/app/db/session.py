from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings
from . import models  # noqa: F401  (registers models on Base.metadata)
from .base import Base


def engine_connect_args(url: str) -> dict:
    """asyncpg through a shared connection pooler (Supabase Pooler / PgBouncer in
    transaction mode, typically port 6543) must not cache prepared statements:
    a cached statement references plan state of a *specific* server connection,
    and the pooler hands you a different one per transaction. Detect the pooler
    from the URL (host/port hint) and disable the cache; direct connections
    (5432) keep full performance."""
    if not url.startswith("postgresql+asyncpg://"):
        return {}
    pooled = "pooler.supabase.com" in url or ":6543" in url or "pgbouncer" in url
    return {"statement_cache_size": 0} if pooled else {}


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    connect_args=engine_connect_args(settings.DATABASE_URL),
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Dev convenience: create tables if missing. Adopt Alembic before production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
