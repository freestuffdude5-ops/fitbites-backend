"""Security headers middleware — defense-in-depth for production."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.
    
    Covers OWASP recommended headers for API servers.
    """

    # Auth/admin endpoints get stricter caching
    _NO_CACHE_PREFIXES = ("/api/v1/auth/", "/api/v1/me/", "/api/v1/admin/")

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking (API shouldn't be framed)
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy — don't leak full URL to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy — disable features we don't need
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # Strict Transport Security (HTTPS only, 1 year)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Cache control: no-store for auth/admin, permissive for public
        path = request.url.path
        if any(path.startswith(p) for p in self._NO_CACHE_PREFIXES):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response
