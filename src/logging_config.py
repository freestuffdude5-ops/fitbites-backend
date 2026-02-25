"""Structured JSON logging for production observability.

In dev: human-readable format
In prod (LOG_FORMAT=json): JSON lines for log aggregators (Datadog, CloudWatch, etc.)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit structured JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log["request_id"] = record.request_id
        return json.dumps(log, default=str)


def setup_logging():
    """Configure logging based on environment."""
    log_format = os.getenv("LOG_FORMAT", "text")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
