"""Meal plan database tables."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Date, DateTime, JSON,
    ForeignKey, Index, UniqueConstraint
)

from src.db.tables import Base


class MealPlanRow(Base):
    """Weekly meal plan with daily calorie/macro targets."""
    __tablename__ = "meal_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False, default="My Meal Plan")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    # Daily targets
    daily_calories = Column(Integer, nullable=True)
    daily_protein_g = Column(Float, nullable=True)
    daily_carbs_g = Column(Float, nullable=True)
    daily_fat_g = Column(Float, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_meal_plans_user_dates", "user_id", "start_date"),
    )


class MealPlanEntryRow(Base):
    """Individual meal slot in a plan (e.g., Monday breakfast)."""
    __tablename__ = "meal_plan_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = Column(String(36), ForeignKey("meal_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    day_index = Column(Integer, nullable=False)  # 0=Mon, 6=Sun (or offset from start_date)
    meal_type = Column(String(20), nullable=False)  # breakfast, lunch, dinner, snack
    servings = Column(Float, default=1.0)
    notes = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_entries_plan_day", "plan_id", "day_index"),
        UniqueConstraint("plan_id", "day_index", "meal_type", "recipe_id", name="uq_plan_slot_recipe"),
    )
