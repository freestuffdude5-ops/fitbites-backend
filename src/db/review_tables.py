"""Recipe reviews, ratings, and cooking history tables."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, JSON, Boolean,
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
)

from src.db.tables import Base


class RecipeReviewRow(Base):
    """User reviews/ratings for recipes — social proof + engagement."""
    __tablename__ = "recipe_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    title = Column(String(200), nullable=True)
    body = Column(Text, nullable=True)
    made_it = Column(Boolean, default=False)  # "I made this" badge
    photos = Column(JSON, default=list)  # URLs of user-submitted photos
    helpful_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_user_recipe_review"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range"),
        Index("ix_review_recipe_rating", "recipe_id", "rating"),
    )


class CookingLogRow(Base):
    """Tracks when a user cooks a recipe — retention + personalization signal."""
    __tablename__ = "cooking_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    cooked_at = Column(DateTime, default=lambda: datetime.utcnow())
    servings = Column(Float, default=1.0)
    notes = Column(Text, nullable=True)
    rating = Column(Integer, nullable=True)  # Quick rating after cooking

    __table_args__ = (
        Index("ix_cooking_log_user_date", "user_id", "cooked_at"),
    )


class ReviewHelpfulRow(Base):
    """Track which reviews a user found helpful — prevents duplicate votes."""
    __tablename__ = "review_helpful"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    review_id = Column(String(36), ForeignKey("recipe_reviews.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        UniqueConstraint("user_id", "review_id", name="uq_user_review_helpful"),
    )
