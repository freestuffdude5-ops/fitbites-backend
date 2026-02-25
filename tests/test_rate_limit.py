"""Tests for rate limiting middleware."""
from __future__ import annotations

import pytest
from src.middleware.rate_limit import RateLimitStore


def test_allows_within_limit():
    store = RateLimitStore()
    for i in range(5):
        allowed, count = store.check_and_record("test-key", 10, 60)
        assert allowed is True
        assert count == i + 1


def test_blocks_over_limit():
    store = RateLimitStore()
    for _ in range(10):
        store.check_and_record("block-key", 10, 60)
    allowed, count = store.check_and_record("block-key", 10, 60)
    assert allowed is False
    assert count == 10


def test_separate_keys():
    store = RateLimitStore()
    for _ in range(10):
        store.check_and_record("key-a", 10, 60)
    # Different key should still be allowed
    allowed, _ = store.check_and_record("key-b", 10, 60)
    assert allowed is True


def test_cleanup_removes_stale():
    store = RateLimitStore()
    store._windows["stale-key"]  # Create empty window
    store._cleanup_interval = 0  # Force cleanup on next check
    store.check_and_record("active-key", 10, 60)
    assert "stale-key" not in store._windows


# Integration tests via API client

@pytest.mark.asyncio
async def test_rate_limit_headers(client):
    """API responses include rate limit headers."""
    resp = await client.get("/api/v1/recipes")
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers


@pytest.mark.asyncio
async def test_health_not_rate_limited(client):
    """Health endpoint is exempt from rate limiting."""
    for _ in range(5):
        resp = await client.get("/health")
        assert resp.status_code == 200
    # Should not have rate limit headers
    resp = await client.get("/health")
    assert "x-ratelimit-limit" not in resp.headers
