"""Request timing middleware — logs every API call with duration."""
from __future__ import annotations

import hashlib
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.db.engine import async_session
from src.analytics.tables import RequestLog

logger = logging.getLogger(__name__)

# Paths to skip logging (health checks, docs)
SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """Logs request method, path, status, duration to DB. Non-blocking."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # Fire-and-forget DB write
        try:
            client_ip = request.client.host if request.client else "unknown"
            ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
            ua = (request.headers.get("user-agent") or "")[:500]

            async with async_session() as session:
                session.add(RequestLog(
                    method=request.method,
                    path=request.url.path[:500],
                    status_code=response.status_code,
                    duration_ms=round(duration_ms, 2),
                    user_agent=ua,
                    ip_hash=ip_hash,
                ))
                await session.commit()
        except Exception:
            logger.debug("Failed to log request", exc_info=True)

        # Add timing header for client debugging
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        return response
