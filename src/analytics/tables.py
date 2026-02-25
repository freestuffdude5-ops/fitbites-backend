"""Analytics database tables for event tracking, request logs, and metrics."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, Text, DateTime, JSON, Index
from src.db.tables import Base


class AnalyticsEvent(Base):
    """Client-side analytics events (app_open, recipe_view, affiliate_click, etc.)."""
    __tablename__ = "analytics_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(36), nullable=True)
    platform = Column(String(20), nullable=True)  # ios, android, web
    app_version = Column(String(20), nullable=True)
    properties = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=lambda: datetime.utcnow(), index=True)
    received_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        Index("ix_events_event_ts", "event", "timestamp"),
        Index("ix_events_user_ts", "user_id", "timestamp"),
    )


class RequestLog(Base):
    """Server-side request performance log."""
    __tablename__ = "request_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    user_agent = Column(String(500), nullable=True)
    ip_hash = Column(String(16), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.utcnow(), index=True)

    __table_args__ = (
        Index("ix_reqlog_path_ts", "path", "timestamp"),
    )
