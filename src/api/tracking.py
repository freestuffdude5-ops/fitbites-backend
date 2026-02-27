"""Calorie Tracking API — /api/v1/tracking endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tracking_tables import MealLogRow, UserGoalRow
from src.auth import require_user
from src.db.user_tables import UserRow

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class LogMealRequest(BaseModel):
    name: str = Field(..., max_length=300)
    calories: float = Field(..., ge=0)
    protein: float = Field(0, ge=0)
    carbs: float = Field(0, ge=0)
    fat: float = Field(0, ge=0)
    timestamp: Optional[datetime] = None


class MealLogResponse(BaseModel):
    id: str
    name: str
    calories: float
    protein: float
    carbs: float
    fat: float
    logged_at: datetime


class MacroTotals(BaseModel):
    calories: float
    protein: float
    carbs: float
    fat: float


class DailySummaryResponse(BaseModel):
    date: str
    eaten: MacroTotals
    goal: MacroTotals
    remaining: MacroTotals
    meal_count: int


class DailyGoalRequest(BaseModel):
    daily_calories: float = Field(..., ge=0)
    daily_protein: float = Field(0, ge=0)
    daily_carbs: float = Field(0, ge=0)
    daily_fat: float = Field(0, ge=0)


class DailyGoalResponse(BaseModel):
    daily_calories: float
    daily_protein: float
    daily_carbs: float
    daily_fat: float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/log-meal", response_model=MealLogResponse, status_code=201)
async def log_meal(
    body: LogMealRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Log a meal with nutritional info."""
    row = MealLogRow(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=body.name,
        calories=body.calories,
        protein=body.protein,
        carbs=body.carbs,
        fat=body.fat,
        logged_at=body.timestamp or datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()
    return MealLogResponse(
        id=row.id, name=row.name, calories=row.calories,
        protein=row.protein, carbs=row.carbs, fat=row.fat, logged_at=row.logged_at,
    )


@router.get("/daily-summary", response_model=DailySummaryResponse)
async def daily_summary(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get today's calorie/macro totals vs goals."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    result = await session.execute(
        select(
            func.coalesce(func.sum(MealLogRow.calories), 0),
            func.coalesce(func.sum(MealLogRow.protein), 0),
            func.coalesce(func.sum(MealLogRow.carbs), 0),
            func.coalesce(func.sum(MealLogRow.fat), 0),
            func.count(MealLogRow.id),
        ).where(
            MealLogRow.user_id == user.id,
            MealLogRow.logged_at >= today_start,
            MealLogRow.logged_at < today_end,
        )
    )
    row = result.one()
    eaten = MacroTotals(calories=row[0], protein=row[1], carbs=row[2], fat=row[3])

    # Get goals
    goal_row = await session.get(UserGoalRow, user.id)
    if goal_row:
        goal = MacroTotals(
            calories=goal_row.daily_calories, protein=goal_row.daily_protein,
            carbs=goal_row.daily_carbs, fat=goal_row.daily_fat,
        )
    else:
        goal = MacroTotals(calories=2000, protein=150, carbs=250, fat=65)

    remaining = MacroTotals(
        calories=max(0, goal.calories - eaten.calories),
        protein=max(0, goal.protein - eaten.protein),
        carbs=max(0, goal.carbs - eaten.carbs),
        fat=max(0, goal.fat - eaten.fat),
    )

    return DailySummaryResponse(
        date=today_start.strftime("%Y-%m-%d"),
        eaten=eaten, goal=goal, remaining=remaining, meal_count=row[4],
    )


@router.get("/history", response_model=list[MealLogResponse])
async def history(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get past 7 days of meal logs."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    result = await session.execute(
        select(MealLogRow)
        .where(MealLogRow.user_id == user.id, MealLogRow.logged_at >= since)
        .order_by(MealLogRow.logged_at.desc())
    )
    rows = result.scalars().all()
    return [
        MealLogResponse(
            id=r.id, name=r.name, calories=r.calories,
            protein=r.protein, carbs=r.carbs, fat=r.fat, logged_at=r.logged_at,
        )
        for r in rows
    ]


@router.put("/daily-goal", response_model=DailyGoalResponse)
async def set_daily_goal(
    body: DailyGoalRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Set or update daily calorie/macro goals."""
    goal_row = await session.get(UserGoalRow, user.id)
    if goal_row:
        goal_row.daily_calories = body.daily_calories
        goal_row.daily_protein = body.daily_protein
        goal_row.daily_carbs = body.daily_carbs
        goal_row.daily_fat = body.daily_fat
    else:
        goal_row = UserGoalRow(
            user_id=user.id,
            daily_calories=body.daily_calories,
            daily_protein=body.daily_protein,
            daily_carbs=body.daily_carbs,
            daily_fat=body.daily_fat,
        )
        session.add(goal_row)
    await session.commit()
    return DailyGoalResponse(
        daily_calories=goal_row.daily_calories,
        daily_protein=goal_row.daily_protein,
        daily_carbs=goal_row.daily_carbs,
        daily_fat=goal_row.daily_fat,
    )
