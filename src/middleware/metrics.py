"""Prometheus-compatible metrics endpoint and request tracking middleware."""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


class _Metrics:
    """Thread-safe in-memory metrics collector."""

    def __init__(self):
        self._lock = Lock()
        self.request_count: dict[tuple[str, str, int], int] = defaultdict(int)
        self.request_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.request_duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.active_requests = 0
        self.startup_time = time.time()

    def record(self, method: str, path: str, status: int, duration: float):
        with self._lock:
            self.request_count[(method, path, status)] += 1
            self.request_duration_sum[(method, path)] += duration
            self.request_duration_count[(method, path)] += 1

    def inc_active(self):
        with self._lock:
            self.active_requests += 1

    def dec_active(self):
        with self._lock:
            self.active_requests -= 1

    def render(self) -> str:
        lines: list[str] = []
        lines.append("# HELP fitbites_http_requests_total Total HTTP requests")
        lines.append("# TYPE fitbites_http_requests_total counter")
        with self._lock:
            for (method, path, status), count in sorted(self.request_count.items()):
                lines.append(
                    f'fitbites_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )

            lines.append("")
            lines.append("# HELP fitbites_http_request_duration_seconds HTTP request duration")
            lines.append("# TYPE fitbites_http_request_duration_seconds summary")
            for (method, path), total in sorted(self.request_duration_sum.items()):
                count = self.request_duration_count[(method, path)]
                lines.append(
                    f'fitbites_http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {total:.6f}'
                )
                lines.append(
                    f'fitbites_http_request_duration_seconds_count{{method="{method}",path="{path}"}} {count}'
                )

            lines.append("")
            lines.append("# HELP fitbites_active_requests Current in-flight requests")
            lines.append("# TYPE fitbites_active_requests gauge")
            lines.append(f"fitbites_active_requests {self.active_requests}")

            lines.append("")
            lines.append("# HELP fitbites_uptime_seconds Seconds since process start")
            lines.append("# TYPE fitbites_uptime_seconds gauge")
            lines.append(f"fitbites_uptime_seconds {time.time() - self.startup_time:.1f}")

        return "\n".join(lines) + "\n"


metrics = _Metrics()


def _normalize_path(path: str) -> str:
    """Collapse IDs in paths to reduce cardinality. /recipes/123 -> /recipes/:id"""
    parts = path.rstrip("/").split("/")
    normalized = []
    for part in parts:
        if part.isdigit() or (len(part) > 20 and part.replace("-", "").isalnum()):
            normalized.append(":id")
        else:
            normalized.append(part)
    return "/".join(normalized) or "/"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/metrics":
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

        metrics.inc_active()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration = time.perf_counter() - start
            metrics.record(
                request.method,
                _normalize_path(request.url.path),
                response.status_code,
                duration,
            )
            return response
        except Exception:
            duration = time.perf_counter() - start
            metrics.record(request.method, _normalize_path(request.url.path), 500, duration)
            raise
        finally:
            metrics.dec_active()
