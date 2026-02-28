#!/usr/bin/env python3
"""Drop and recreate auth tables with timezone-aware columns."""
import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return 1
    
    # Convert postgres:// to postgresql+asyncpg://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif not database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    engine = create_async_engine(database_url, echo=True)
    
    async with engine.begin() as conn:
        # Drop auth-related tables
        print("Dropping auth tables...")
        await conn.execute("DROP TABLE IF EXISTS grocery_lists CASCADE")
        await conn.execute("DROP TABLE IF EXISTS saved_recipes CASCADE")
        await conn.execute("DROP TABLE IF EXISTS user_goals CASCADE")
        await conn.execute("DROP TABLE IF EXISTS meal_log_entries CASCADE")
        await conn.execute("DROP TABLE IF EXISTS daily_logs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS meal_plan_entries CASCADE")
        await conn.execute("DROP TABLE IF EXISTS meal_plans CASCADE")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE")
        print("✓ Auth tables dropped. They will be recreated on next backend startup.")
    
    await engine.dispose()
    return 0

if __name__ == "__main__":
    exit(asyncio.run(main()))
