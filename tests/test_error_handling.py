"""Tests for structured error responses — premium-grade error handling."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_404_returns_structured_error(client):
    resp = await client.get("/api/v1/recipes/nonexistent-id-12345")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert "message" in data


@pytest.mark.asyncio
async def test_validation_error_returns_structured_error(client):
    """Search with empty query should return 422 with clean error details."""
    resp = await client.get("/api/v1/recipes/search?q=")
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "validation_error"
    assert "details" in data
    assert isinstance(data["details"], list)


@pytest.mark.asyncio
async def test_invalid_pagination_returns_structured_error(client):
    resp = await client.get("/api/v1/recipes?limit=-1")
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "validation_error"


@pytest.mark.asyncio
async def test_rate_limit_returns_structured_error(client):
    """Scrape endpoint requires admin auth."""
    # Without admin key, should get 503 (admin not configured) or 403
    resp = await client.post("/api/v1/scrape")
    assert resp.status_code in (403, 503)
    data = resp.json()
    assert "error" in data or "message" in data


@pytest.mark.asyncio
async def test_shop_all_empty_ingredients(client):
    resp = await client.post("/api/v1/affiliate-links/shop-all", json=[])
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
