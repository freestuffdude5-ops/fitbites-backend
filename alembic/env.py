"""Alembic env.py — configured for FitBites async SQLAlchemy."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from config.settings import settings

# Import all models so Alembic sees them
from src.db.tables import Base, RecipeRow  # noqa: F401
from src.db.user_tables import UserRow, SavedRecipeRow, GroceryListRow  # noqa: F401
from src.db.meal_plan_tables import MealPlanRow, MealPlanEntryRow  # noqa: F401
import src.analytics.tables  # noqa: F401
import src.db.tracking_tables  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Get database URL, converting async drivers for Alembic (sync)."""
    url = settings.DATABASE_URL
    # Alembic needs sync driver
    if "aiosqlite" in url:
        return url.replace("sqlite+aiosqlite", "sqlite")
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL script."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to DB directly."""
    from sqlalchemy import create_engine

    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
