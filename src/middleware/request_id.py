"""Request ID tracing middleware — adds X-Request-ID to every response."""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context var accessible from anywhere during a request lifecycle
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request/response for tracing.

    - If the client sends X-Request-ID, we honor it
    - Otherwise we generate a UUID4
    - The ID is set in a ContextVar so loggers can include it
    - Response always includes X-Request-ID header
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
