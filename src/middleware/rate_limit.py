"""Rate limiting middleware — in-memory with sliding window.

Production-grade rate limiter that protects against:
- Brute-force auth attacks (tight limit on /auth/)
- API abuse (general limit on all endpoints)
- Scrape endpoint abuse (already has its own cooldown, but this adds IP-level)

Uses in-memory storage (works for single-instance). For multi-instance,
swap _store for Redis backend.
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


@dataclass
class _RateWindow:
    """Sliding window counter for a single client."""
    timestamps: list[float] = field(default_factory=list)

    def count_in_window(self, window_seconds: float) -> int:
        now = time.monotonic()
        cutoff = now - window_seconds
        # Prune old entries
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        return len(self.timestamps)

    def record(self) -> None:
        self.timestamps.append(time.monotonic())


class RateLimitStore:
    """In-memory rate limit storage with automatic cleanup."""

    def __init__(self):
        self._windows: dict[str, _RateWindow] = defaultdict(_RateWindow)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 300  # 5 minutes

    def check_and_record(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Check if request is allowed, record it if so.

        Returns (allowed, current_count).
        """
        self._maybe_cleanup()
        window = self._windows[key]
        count = window.count_in_window(window_seconds)
        if count >= limit:
            return False, count
        window.record()
        return True, count + 1

    def _maybe_cleanup(self):
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        # Remove entries with no recent activity
        stale = [k for k, w in self._windows.items() if not w.timestamps]
        for k in stale:
            del self._windows[k]


# Global store
_store = RateLimitStore()


def reset_store():
    """Reset rate limit state — used in tests."""
    _store._windows.clear()

# Route-specific limits
_RATE_LIMITS: list[tuple[str, int, int]] = [
    # (path_prefix, requests, window_seconds)
    ("/api/v1/auth/", 10, 60),       # 10 auth attempts per minute
    ("/api/v1/scrape", 3, 300),      # 3 scrape triggers per 5 min
    ("/go/", 60, 60),                # 60 redirects per minute
    ("/api/", 120, 60),              # 120 API calls per minute (general)
]

# Paths exempt from rate limiting
_EXEMPT = {"/health", "/", "/docs", "/openapi.json"}


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _find_limit(path: str) -> tuple[int, int] | None:
    """Find the most specific rate limit for a path."""
    if path in _EXEMPT:
        return None
    for prefix, limit, window in _RATE_LIMITS:
        if path.startswith(prefix):
            return limit, window
    return 120, 60  # Default: 120/min


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for IP-based rate limiting."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        rate = _find_limit(path)
        if rate is None:
            return await call_next(request)

        limit, window = rate
        client_ip = _get_client_ip(request)
        key = f"{client_ip}:{path.split('/')[1]}"  # Group by IP + first path segment

        # More specific key for auth to prevent cross-endpoint abuse
        if path.startswith("/api/v1/auth/"):
            key = f"{client_ip}:auth"

        allowed, count = _store.check_and_record(key, limit, window)

        if not allowed:
            logger.warning(f"Rate limited: {client_ip} on {path} ({count}/{limit} in {window}s)")
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "message": "Too many requests. Please try again later.",
                    "retry_after": window,
                },
                headers={"Retry-After": str(window)},
            )

        response = await call_next(request)
        # Add rate limit headers for client awareness
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response
