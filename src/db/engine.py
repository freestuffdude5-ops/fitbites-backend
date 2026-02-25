"""Async SQLAlchemy engine + session factory.

Supports both SQLite (dev) and PostgreSQL (prod) with appropriate pool settings.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from config.settings import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# PostgreSQL gets connection pooling; SQLite uses NullPool equivalent
_engine_kwargs: dict = {
    "echo": False,
    "future": True,
}

if not _is_sqlite:
    # Production PostgreSQL pool settings
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,  # Recycle connections every 30 min
        "pool_pre_ping": True,  # Verify connections before use
    })

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """Dependency for FastAPI — yields an async session."""
    async with async_session() as session:
        yield session
