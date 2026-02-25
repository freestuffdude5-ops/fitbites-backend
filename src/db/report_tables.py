"""Content reporting tables — required for App Store compliance."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Integer,
    ForeignKey, Index, UniqueConstraint
)

from src.db.tables import Base


def _now():
    return datetime.now(timezone.utc)


class ReportRow(Base):
    """User-submitted content reports for moderation."""
    __tablename__ = "reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type = Column(String(20), nullable=False)  # recipe, comment, review, user
    content_id = Column(String(36), nullable=False)
    reason = Column(String(50), nullable=False)  # spam, inappropriate, misleading, harmful, copyright, other
    details = Column(Text, nullable=True)
    status = Column(String(20), default="pending", nullable=False)  # pending, reviewed, resolved, dismissed
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("reporter_id", "content_type", "content_id", name="uq_user_report"),
        Index("ix_report_status", "status"),
        Index("ix_report_content", "content_type", "content_id"),
    )
