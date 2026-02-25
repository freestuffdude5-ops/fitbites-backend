"""Collection tables — first-class recipe collections/folders."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Boolean,
    ForeignKey, Index, UniqueConstraint
)

from src.db.tables import Base


def _now():
    return datetime.now(timezone.utc)


class CollectionRow(Base):
    """A named collection of recipes (e.g. 'Weeknight Dinners', 'Meal Prep')."""
    __tablename__ = "collections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    emoji = Column(String(10), nullable=True)  # Collection icon emoji
    cover_recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    position = Column(Integer, default=0, nullable=False)  # For manual ordering
    recipe_count = Column(Integer, default=0, nullable=False)  # Denormalized for perf
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_collection_name"),
        Index("ix_collection_user_position", "user_id", "position"),
    )


class CollectionItemRow(Base):
    """Recipe membership in a collection."""
    __tablename__ = "collection_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id = Column(String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    added_by = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notes = Column(Text, nullable=True)  # Per-recipe notes within collection
    position = Column(Integer, default=0, nullable=False)
    added_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("collection_id", "recipe_id", name="uq_collection_recipe"),
        Index("ix_collection_item_position", "collection_id", "position"),
    )
