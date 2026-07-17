from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings
from . import models  # noqa: F401  (registers models on Base.metadata)
from .base import Base

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, echo=settings.DEBUG)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Dev convenience: create tables if missing. Adopt Alembic before production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
