"""Social tables: follows, activity feed, recipe shares."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, JSON,
    ForeignKey, Index, UniqueConstraint,
)

from src.db.tables import Base


class FollowRow(Base):
    """User-to-user follow relationship."""
    __tablename__ = "follows"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    follower_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    following_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follow_pair"),
        Index("ix_follow_follower", "follower_id"),
        Index("ix_follow_following", "following_id"),
    )


class ActivityRow(Base):
    """Activity feed events — denormalized for fast feed queries."""
    __tablename__ = "activities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    action = Column(String(50), nullable=False)  # cooked, saved, reviewed, shared
    recipe_id = Column(
        String(36), ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    target_user_id = Column(String(36), nullable=True)  # e.g. who they followed
    extra = Column(JSON, default=dict)  # extra context (rating, photo_url, etc.)
    created_at = Column(DateTime, default=lambda: datetime.utcnow(), index=True)

    __table_args__ = (
        Index("ix_activity_user_time", "user_id", "created_at"),
    )


class RecipeShareRow(Base):
    """Shared recipe links — trackable shares for viral attribution."""
    __tablename__ = "recipe_shares"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    recipe_id = Column(
        String(36), ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    share_code = Column(String(12), nullable=False, unique=True, index=True)
    platform = Column(String(50), nullable=True)  # instagram, messages, twitter, etc.
    clicks = Column(String(36), default="0")  # track opens
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
