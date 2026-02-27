"""Recipe Integration API — connect recipes to daily nutrition tracking.

Endpoints:
  POST /api/v1/recipes/log-to-tracker  — Log a recipe's macros to today's daily log
  GET  /api/v1/recipes/{id}/nutrition   — Get recipe nutrition summary
  POST /api/v1/recipes/save-favorite    — Save recipe to user favorites
  GET  /api/v1/recipes/my-favorites     — Get user's saved recipes
  GET  /api/v1/tracking/daily           — Get today's (or any date's) nutrition log
  GET  /api/v1/tracking/log-meal        — ECHO integration endpoint (internal)
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_user
from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow, SavedRecipeRow
from src.db.tracking_tables import DailyLogRow, MealLogEntryRow

router = APIRouter(prefix="/api/v1", tags=["recipe-tracking"])


# ── Request / Response Models ─────────────────────────────────────────────────

class LogToTrackerRequest(BaseModel):
    recipe_id: str
    portion: float = Field(1.0, gt=0, le=10.0, description="Portion multiplier: 0.5=half, 1=full, 2=double")
    meal_type: str = Field("meal", pattern="^(breakfast|lunch|dinner|snack|meal)$")


class LogToTrackerResponse(BaseModel):
    status: str
    entry_id: str
    recipe_title: str
    portion: float
    logged_nutrition: dict  # {calories, protein_g, carbs_g, fat_g}
    daily_totals: dict      # updated daily totals


class NutritionSummary(BaseModel):
    recipe_id: str
    title: str
    servings: int
    per_serving: dict       # {calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g}
    full_recipe: dict       # total for entire recipe
    half_recipe: dict       # convenience: half portion


class SaveFavoriteRequest(BaseModel):
    recipe_id: str
    collection: Optional[str] = None
    notes: Optional[str] = None


class DailyLogResponse(BaseModel):
    date: str
    totals: dict
    meals: list


# ── Helpers ───────────────────────────────────────────────────────────────────

def _calc_macros(row: RecipeRow, portion: float = 1.0) -> dict:
    """Calculate macros for a given portion of a recipe."""
    return {
        "calories": int(math.ceil((row.calories or 0) * portion)),
        "protein_g": round((row.protein_g or 0) * portion, 1),
        "carbs_g": round((row.carbs_g or 0) * portion, 1),
        "fat_g": round((row.fat_g or 0) * portion, 1),
        "fiber_g": round((row.fiber_g or 0) * portion, 1),
        "sugar_g": round((row.sugar_g or 0) * portion, 1),
    }


async def _get_or_create_daily_log(
    session: AsyncSession, user_id: str, log_date: date
) -> DailyLogRow:
    """Get or create a daily log row for user + date."""
    result = await session.execute(
        select(DailyLogRow).where(
            DailyLogRow.user_id == user_id,
            DailyLogRow.log_date == log_date,
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        daily = DailyLogRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            log_date=log_date,
            total_calories=0,
            total_protein_g=0.0,
            total_carbs_g=0.0,
            total_fat_g=0.0,
            total_fiber_g=0.0,
        )
        session.add(daily)
        await session.flush()
    return daily


async def _get_recipe_or_404(session: AsyncSession, recipe_id: str) -> RecipeRow:
    """Fetch recipe by ID or raise 404."""
    result = await session.execute(
        select(RecipeRow).where(RecipeRow.id == recipe_id)
    )
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return recipe


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/recipes/log-to-tracker", response_model=LogToTrackerResponse)
async def log_recipe_to_tracker(
    req: LogToTrackerRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Log a recipe's nutrition to today's daily tracker.
    
    Supports portion sizes: 0.5 (half), 1.0 (full), 2.0 (double), etc.
    Automatically creates today's daily log if it doesn't exist.
    """
    recipe = await _get_recipe_or_404(session, req.recipe_id)
    macros = _calc_macros(recipe, req.portion)

    today = date.today()
    daily = await _get_or_create_daily_log(session, user.id, today)

    # Create meal log entry
    entry = MealLogEntryRow(
        id=str(uuid.uuid4()),
        user_id=user.id,
        daily_log_id=daily.id,
        recipe_id=recipe.id,
        meal_type=req.meal_type,
        portion=req.portion,
        calories=macros["calories"],
        protein_g=macros["protein_g"],
        carbs_g=macros["carbs_g"],
        fat_g=macros["fat_g"],
        recipe_title=recipe.title,
    )
    session.add(entry)

    # Update daily totals
    daily.total_calories = (daily.total_calories or 0) + macros["calories"]
    daily.total_protein_g = round((daily.total_protein_g or 0) + macros["protein_g"], 1)
    daily.total_carbs_g = round((daily.total_carbs_g or 0) + macros["carbs_g"], 1)
    daily.total_fat_g = round((daily.total_fat_g or 0) + macros["fat_g"], 1)
    daily.total_fiber_g = round((daily.total_fiber_g or 0) + macros.get("fiber_g", 0), 1)
    daily.updated_at = datetime.now(timezone.utc)

    await session.commit()

    return LogToTrackerResponse(
        status="logged",
        entry_id=entry.id,
        recipe_title=recipe.title,
        portion=req.portion,
        logged_nutrition={k: macros[k] for k in ("calories", "protein_g", "carbs_g", "fat_g")},
        daily_totals={
            "calories": daily.total_calories,
            "protein_g": daily.total_protein_g,
            "carbs_g": daily.total_carbs_g,
            "fat_g": daily.total_fat_g,
        },
    )


@router.get("/recipes/{recipe_id}/nutrition", response_model=NutritionSummary)
async def get_recipe_nutrition(
    recipe_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get detailed nutrition summary for a recipe.
    
    Returns per-serving, full-recipe, and half-recipe breakdowns.
    No auth required — public endpoint.
    """
    recipe = await _get_recipe_or_404(session, recipe_id)
    servings = recipe.servings or 1

    full = _calc_macros(recipe, 1.0)
    per_serving = _calc_macros(recipe, 1.0 / servings) if servings > 1 else full
    half = _calc_macros(recipe, 0.5)

    return NutritionSummary(
        recipe_id=recipe.id,
        title=recipe.title,
        servings=servings,
        per_serving=per_serving,
        full_recipe=full,
        half_recipe=half,
    )


@router.post("/recipes/save-favorite")
async def save_favorite(
    req: SaveFavoriteRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Save a recipe to user's favorites with optional collection and notes."""
    await _get_recipe_or_404(session, req.recipe_id)

    # Check if already saved
    existing = await session.execute(
        select(SavedRecipeRow).where(
            SavedRecipeRow.user_id == user.id,
            SavedRecipeRow.recipe_id == req.recipe_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_saved", "recipe_id": req.recipe_id}

    saved = SavedRecipeRow(
        user_id=user.id,
        recipe_id=req.recipe_id,
        collection=req.collection,
        notes=req.notes,
    )
    session.add(saved)
    await session.commit()
    return {"status": "saved", "recipe_id": req.recipe_id}


@router.get("/recipes/my-favorites")
async def get_my_favorites(
    collection: Optional[str] = Query(None, description="Filter by collection name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get user's saved/favorite recipes with nutrition info."""
    stmt = (
        select(RecipeRow, SavedRecipeRow.collection, SavedRecipeRow.notes, SavedRecipeRow.saved_at)
        .join(SavedRecipeRow, SavedRecipeRow.recipe_id == RecipeRow.id)
        .where(SavedRecipeRow.user_id == user.id)
    )
    if collection:
        stmt = stmt.where(SavedRecipeRow.collection == collection)
    stmt = stmt.order_by(SavedRecipeRow.saved_at.desc()).limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = result.all()

    favorites = []
    for recipe, coll, notes, saved_at in rows:
        favorites.append({
            "recipe_id": recipe.id,
            "title": recipe.title,
            "thumbnail_url": recipe.thumbnail_url,
            "collection": coll,
            "notes": notes,
            "saved_at": saved_at.isoformat() if saved_at else None,
            "nutrition": {
                "calories": recipe.calories,
                "protein_g": recipe.protein_g,
                "carbs_g": recipe.carbs_g,
                "fat_g": recipe.fat_g,
            },
        })

    return {"data": favorites, "total": len(favorites)}


@router.get("/tracking/daily")
async def get_daily_log(
    log_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get daily nutrition log with all meal entries.
    
    This is the endpoint ECHO's tracking system calls to display daily progress.
    """
    if log_date:
        try:
            target_date = date.fromisoformat(log_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = date.today()

    # Get daily log
    result = await session.execute(
        select(DailyLogRow).where(
            DailyLogRow.user_id == user.id,
            DailyLogRow.log_date == target_date,
        )
    )
    daily = result.scalar_one_or_none()

    if not daily:
        return DailyLogResponse(
            date=target_date.isoformat(),
            totals={"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0},
            meals=[],
        )

    # Get meal entries
    entries_result = await session.execute(
        select(MealLogEntryRow)
        .where(MealLogEntryRow.daily_log_id == daily.id)
        .order_by(MealLogEntryRow.logged_at)
    )
    entries = entries_result.scalars().all()

    meals = [
        {
            "entry_id": e.id,
            "recipe_id": e.recipe_id,
            "recipe_title": e.recipe_title,
            "meal_type": e.meal_type,
            "portion": e.portion,
            "nutrition": {
                "calories": e.calories,
                "protein_g": e.protein_g,
                "carbs_g": e.carbs_g,
                "fat_g": e.fat_g,
            },
            "logged_at": e.logged_at.isoformat() if e.logged_at else None,
        }
        for e in entries
    ]

    return DailyLogResponse(
        date=target_date.isoformat(),
        totals={
            "calories": daily.total_calories or 0,
            "protein_g": daily.total_protein_g or 0,
            "carbs_g": daily.total_carbs_g or 0,
            "fat_g": daily.total_fat_g or 0,
            "fiber_g": daily.total_fiber_g or 0,
        },
        meals=meals,
    )


# NOTE: /tracking/log-meal is now handled by src/api/tracking.py (ECHO's calorie tracking API)
# The old stub here has been removed to avoid route conflicts.
