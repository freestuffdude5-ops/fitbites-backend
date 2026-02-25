"""User-related database tables: profiles, saved recipes, grocery lists."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, JSON, Boolean,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship

from src.db.tables import Base


class UserRow(Base):
    """User profile — supports anonymous (device_id) + authenticated (email+password) users."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # For anonymous users: device_id only. For auth users: email + password_hash.
    device_id = Column(String(64), nullable=True, unique=True, index=True)
    email = Column(String(320), nullable=True, unique=True, index=True)
    password_hash = Column(String(256), nullable=True)  # PBKDF2-SHA256
    display_name = Column(String(100), nullable=True)
    avatar_url = Column(String(2000), nullable=True)

    # Preferences (JSON blob for flexibility)
    preferences = Column(JSON, default=dict)  # e.g. {"dietary": ["keto"], "max_calories": 500}

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_active_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    comments = relationship("CommentRow", back_populates="author", foreign_keys="CommentRow.user_id")
    



class SavedRecipeRow(Base):
    """User's saved/favorited recipes — the core retention feature."""
    __tablename__ = "saved_recipes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    collection = Column(String(100), nullable=True, default=None)  # e.g. "Meal Prep", "Quick Snacks"
    notes = Column(Text, nullable=True)  # personal notes on the recipe
    saved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_user_recipe"),
        Index("ix_saved_user_collection", "user_id", "collection"),
    )


class GroceryListRow(Base):
    """Grocery list — aggregated ingredients from saved recipes."""
    __tablename__ = "grocery_lists"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False, default="My Grocery List")
    items = Column(JSON, default=list)  # [{ingredient, amount, recipe_id, checked}]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
