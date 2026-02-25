"""In-memory response cache middleware for fast reads.

Includes both a Starlette middleware class and low-level cache functions.

Caches GET responses for trending/recipes endpoints for configurable TTL.
This gives <5ms response times for repeated requests — critical for
smooth scrolling and instant search results on the iOS app.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

# Simple TTL cache — no dependencies needed
_cache: dict[str, tuple[float, Any]] = {}
_DEFAULT_TTL = 30  # seconds


def cache_key(path: str, query: str) -> str:
    """Generate a cache key from path + query string."""
    raw = f"{path}?{query}" if query else path
    return hashlib.md5(raw.encode()).hexdigest()


def get_cached(key: str) -> Any | None:
    """Get cached value if still valid."""
    if key in _cache:
        expires, value = _cache[key]
        if time.time() < expires:
            return value
        del _cache[key]
    return None


def set_cached(key: str, value: Any, ttl: int = _DEFAULT_TTL):
    """Store value in cache with TTL."""
    _cache[key] = (time.time() + ttl, value)

    # Evict old entries if cache gets too large (>500 entries)
    if len(_cache) > 500:
        now = time.time()
        expired = [k for k, (exp, _) in _cache.items() if now >= exp]
        for k in expired:
            del _cache[k]


def invalidate_cache():
    """Clear entire cache (called after scrape/write operations)."""
    _cache.clear()


def cache_stats() -> dict:
    """Return cache statistics."""
    now = time.time()
    valid = sum(1 for exp, _ in _cache.values() if now < exp)
    return {
        "total_entries": len(_cache),
        "valid_entries": valid,
        "expired_entries": len(_cache) - valid,
    }


# Paths to cache and their TTLs
_CACHEABLE_PATHS = {
    "/api/v1/trending": 60,
    "/api/v1/recipes": 30,
    "/api/v1/recipes/search": 15,
}


class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """Caches GET responses for read-heavy endpoints.

    This gives <5ms response times for repeated requests — critical for
    smooth iOS scrolling and instant search results.
    """

    async def dispatch(self, request: Request, call_next):
        # Only cache GET requests
        if request.method != "GET":
            response = await call_next(request)
            # Invalidate cache on writes
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                invalidate_cache()
            return response

        # Check if this path is cacheable
        path = request.url.path
        ttl = None
        for cacheable_path, path_ttl in _CACHEABLE_PATHS.items():
            if path.startswith(cacheable_path):
                ttl = path_ttl
                break

        if ttl is None:
            return await call_next(request)

        # Check cache
        key = cache_key(path, str(request.url.query))
        cached = get_cached(key)
        if cached is not None:
            body, status, content_type = cached
            return Response(
                content=body,
                status_code=status,
                headers={"content-type": content_type, "x-cache": "HIT"},
            )

        # Call handler and cache the response
        response = await call_next(request)

        # Only cache successful JSON responses
        if response.status_code == 200:
            body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body += chunk.encode()
                else:
                    body += chunk

            content_type = response.headers.get("content-type", "application/json")
            set_cached(key, (body, response.status_code, content_type), ttl=ttl)

            return Response(
                content=body,
                status_code=response.status_code,
                headers={**dict(response.headers), "x-cache": "MISS"},
            )

        return response
