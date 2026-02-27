"""Daily nutrition tracking tables — log meals from recipes to daily totals."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Date, DateTime, JSON,
    ForeignKey, Index, UniqueConstraint
)

from src.db.tables import Base


class DailyLogRow(Base):
    """One row per user per day — aggregated nutrition totals."""
    __tablename__ = "daily_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date = Column(Date, nullable=False)

    total_calories = Column(Integer, default=0)
    total_protein_g = Column(Float, default=0.0)
    total_carbs_g = Column(Float, default=0.0)
    total_fat_g = Column(Float, default=0.0)
    total_fiber_g = Column(Float, default=0.0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_user_daily_log"),
        Index("ix_daily_logs_user_date", "user_id", "log_date"),
    )


class MealLogEntryRow(Base):
    """Individual meal log entry — tracks each recipe logged with portion info."""
    __tablename__ = "meal_log_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    daily_log_id = Column(String(36), ForeignKey("daily_logs.id", ondelete="CASCADE"), nullable=False)
    recipe_id = Column(String(36), ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)

    # Meal metadata
    meal_type = Column(String(20), nullable=False, default="meal")  # breakfast, lunch, dinner, snack, meal
    portion = Column(Float, nullable=False, default=1.0)  # 1.0 = full, 0.5 = half, 2.0 = double

    # Snapshot of nutrition at time of logging (in case recipe changes later)
    calories = Column(Integer, default=0)
    protein_g = Column(Float, default=0.0)
    carbs_g = Column(Float, default=0.0)
    fat_g = Column(Float, default=0.0)

    recipe_title = Column(String(500), nullable=True)  # denormalized for fast display
    logged_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_meal_log_user", "user_id"),
        Index("ix_meal_log_daily", "daily_log_id"),
    )


# ── Calorie Tracking v2 (standalone meal logs + user goals) ──────────────────

class MealLogRow(Base):
    """Individual meal log — standalone, no recipe dependency required."""
    __tablename__ = "meal_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    calories = Column(Float, nullable=False)
    protein = Column(Float, nullable=False, default=0)
    carbs = Column(Float, nullable=False, default=0)
    fat = Column(Float, nullable=False, default=0)
    logged_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class UserGoalRow(Base):
    """Per-user daily nutrition goals."""
    __tablename__ = "user_goals"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    daily_calories = Column(Float, nullable=False, default=2000)
    daily_protein = Column(Float, nullable=False, default=150)
    daily_carbs = Column(Float, nullable=False, default=250)
    daily_fat = Column(Float, nullable=False, default=65)
