"""Tests for the response cache middleware."""
import time
from src.middleware.cache import get_cached, set_cached, invalidate_cache, cache_stats, cache_key


def test_cache_set_get():
    invalidate_cache()
    set_cached("test1", {"data": [1, 2, 3]}, ttl=10)
    result = get_cached("test1")
    assert result == {"data": [1, 2, 3]}


def test_cache_miss():
    invalidate_cache()
    assert get_cached("nonexistent") is None


def test_cache_expiry():
    invalidate_cache()
    set_cached("expire_me", "value", ttl=0)
    time.sleep(0.01)
    assert get_cached("expire_me") is None


def test_cache_invalidate():
    set_cached("a", 1)
    set_cached("b", 2)
    invalidate_cache()
    assert get_cached("a") is None
    assert get_cached("b") is None


def test_cache_key_generation():
    k1 = cache_key("/api/v1/trending", "limit=20")
    k2 = cache_key("/api/v1/trending", "limit=20")
    k3 = cache_key("/api/v1/trending", "limit=50")
    assert k1 == k2
    assert k1 != k3


def test_cache_stats():
    invalidate_cache()
    set_cached("x", 1, ttl=60)
    set_cached("y", 2, ttl=0)
    time.sleep(0.01)
    stats = cache_stats()
    assert stats["total_entries"] == 2
    assert stats["valid_entries"] == 1
    assert stats["expired_entries"] == 1
