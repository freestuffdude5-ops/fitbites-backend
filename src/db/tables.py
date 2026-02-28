"""SQLAlchemy ORM models for FitBites database."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, JSON, Enum as SAEnum, Index
)
from sqlalchemy.orm import DeclarativeBase

from src.models import Platform


class Base(DeclarativeBase):
    pass


class RecipeRow(Base):
    __tablename__ = "recipes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(500), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Creator info (flattened — no need for separate table in MVP)
    creator_username = Column(String(200), nullable=False)
    creator_display_name = Column(String(200), nullable=True)
    creator_platform = Column(SAEnum(Platform), nullable=False)
    creator_profile_url = Column(String(1000), nullable=False)
    creator_avatar_url = Column(String(1000), nullable=True)
    creator_follower_count = Column(Integer, nullable=True)

    platform = Column(SAEnum(Platform), nullable=False, index=True)
    source_url = Column(String(2000), nullable=False, unique=True)
    thumbnail_url = Column(String(2000), nullable=True)
    video_url = Column(String(2000), nullable=True)

    # Stored as JSON arrays
    ingredients = Column(JSON, default=list)  # list[Ingredient dict]
    steps = Column(JSON, default=list)  # list[str]
    tags = Column(JSON, default=list)  # list[str]

    # Nutrition (flattened)
    calories = Column(Integer, nullable=True)
    protein_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    fiber_g = Column(Float, nullable=True)
    sugar_g = Column(Float, nullable=True)
    servings = Column(Integer, default=1)

    # Engagement
    views = Column(Integer, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)

    # Metadata
    cook_time_minutes = Column(Integer, nullable=True)
    difficulty = Column(String(20), nullable=True)
    virality_score = Column(Float, nullable=True, index=True)

    scraped_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    published_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_recipes_calories", "calories"),
        Index("ix_recipes_protein", "protein_g"),
    )
