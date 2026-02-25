"""Async SQLAlchemy engine + session factory.

Supports both SQLite (dev) and PostgreSQL (prod) with appropriate pool settings.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from config.settings import settings

# Convert postgresql:// to postgresql+asyncpg:// for async support
_db_url = settings.DATABASE_URL
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

_is_sqlite = _db_url.startswith("sqlite")

# PostgreSQL gets connection pooling; SQLite uses NullPool equivalent
_engine_kwargs: dict = {
    "echo": False,
    "future": True,
}

if not _is_sqlite:
    import ssl as ssl_module
    # Production PostgreSQL pool settings
    ssl_context = ssl_module.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl_module.CERT_NONE
    
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,  # Recycle connections every 30 min
        "pool_pre_ping": True,  # Verify connections before use
        "connect_args": {"ssl": ssl_context},  # SSL required for Railway public endpoint
    })

engine = create_async_engine(_db_url, **_engine_kwargs)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """Dependency for FastAPI — yields an async session."""
    async with async_session() as session:
        yield session
