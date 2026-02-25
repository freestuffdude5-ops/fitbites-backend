"""Recently viewed database table — track user recipe browsing history."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Index

from src.db.tables import Base


class RecentlyViewedRow(Base):
    """Track when user views a recipe (for history/recommendations)."""
    __tablename__ = "recently_viewed"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    viewed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index("ix_recently_viewed_user_time", "user_id", "viewed_at"),
    )
