"""Shared test fixtures — single test DB for all test modules."""
from __future__ import annotations

import os
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.db.tables import Base
from src.db.engine import get_session

# Use a shared in-memory DB with check_same_thread=False and StaticPool
# This ensures all connections see the same in-memory database.
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite+aiosqlite:///file:test?mode=memory&cache=shared&uri=true"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


async def override_get_session():
    async with TestSession() as session:
        yield session


# Import app and override BEFORE any test module imports app
from src.api.main import app  # noqa: E402

app.dependency_overrides[get_session] = override_get_session

# Patch the middleware's async_session and engine to use our test engine
import src.db.engine as _engine_mod
import src.analytics.middleware as _mw_mod
_engine_mod.async_session = TestSession
_engine_mod.engine = test_engine
_mw_mod.async_session = TestSession


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_test_session():
    """Context manager for seeding data in tests."""
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after. Seeds a test recipe."""
    import src.analytics.tables  # noqa: F401
    import src.db.user_tables  # noqa: F401
    import src.db.meal_plan_tables  # noqa: F401
    import src.db.review_tables  # noqa: F401
    from src.db.tables import RecipeRow
    from src.models import Platform

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed a test recipe for tests that need one
    async with TestSession() as session:
        session.add(RecipeRow(
            id="test-recipe-1",
            title="Test Chicken Bowl",
            creator_username="chef",
            creator_platform=Platform.YOUTUBE,
            creator_profile_url="https://example.com",
            platform=Platform.YOUTUBE,
            source_url="https://example.com/test-1",
            ingredients=[{"name": "chicken breast", "quantity": "200g"}, {"name": "rice", "quantity": "1 cup"}],
            steps=["Cook chicken", "Serve with rice"],
            calories=400, protein_g=35, carbs_g=30, fat_g=12,
            virality_score=85, tags=["high-protein"],
        ))
        await session.commit()

    yield

    # Reset rate limiter between tests
    from src.middleware.rate_limit import reset_store
    reset_store()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
