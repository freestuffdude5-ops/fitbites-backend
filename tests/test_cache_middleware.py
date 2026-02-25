"""Tests for the HTTP-level response cache middleware."""
import pytest
from src.middleware.cache import invalidate_cache


@pytest.fixture(autouse=True)
def clear_cache():
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.mark.asyncio
async def test_trending_cache_hit(client):
    """Second request to trending should be a cache HIT."""
    # First request — MISS
    r1 = await client.get("/api/v1/trending?limit=5")
    assert r1.status_code == 200
    assert r1.headers.get("x-cache") == "MISS"

    # Second request — HIT
    r2 = await client.get("/api/v1/trending?limit=5")
    assert r2.status_code == 200
    assert r2.headers.get("x-cache") == "HIT"
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_different_params_different_cache(client):
    """Different query params should not share cache."""
    r1 = await client.get("/api/v1/trending?limit=5")
    r2 = await client.get("/api/v1/trending?limit=10")
    # Both should be MISS (different params)
    assert r1.headers.get("x-cache") == "MISS"
    assert r2.headers.get("x-cache") == "MISS"


@pytest.mark.asyncio
async def test_post_invalidates_cache(client):
    """POST requests should invalidate the cache."""

    # Warm cache
    r1 = await client.get("/api/v1/trending?limit=5")
    assert r1.headers.get("x-cache") == "MISS"

    # POST request — should invalidate
    await client.post("/api/v1/events", json={"event": "test", "user_id": "u1"})

    # Next GET should be MISS again
    r3 = await client.get("/api/v1/trending?limit=5")
    assert r3.headers.get("x-cache") == "MISS"
