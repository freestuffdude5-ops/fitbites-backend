"""Recommendation & Meal Planning API routes."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow
from src.db.meal_plan_tables import MealPlanRow, MealPlanEntryRow
from src.services.recommendations import get_personalized_feed

router = APIRouter(prefix="/api/v1", tags=["recommendations", "meal-plans"])


# ── Personalized Feed ────────────────────────────────────────────────────────

@router.get("/feed/{user_id}")
async def personalized_feed(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    exclude_saved: bool = Query(True, description="Hide already-saved recipes"),
    session: AsyncSession = Depends(get_session),
):
    """Get a personalized recipe feed based on user preferences and history.

    Returns recipes scored and ranked by:
    - Dietary preference match
    - Tag affinity from saved recipes
    - Virality/quality signal
    - Freshness
    - Macro quality (high protein per calorie)

    Feed is diversity-optimized to avoid showing consecutive similar recipes.
    """
    # Verify user exists (but still return generic feed for anonymous)
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    recipes = await get_personalized_feed(
        user_id=user_id,
        session=session,
        limit=limit,
        offset=offset,
        exclude_saved=exclude_saved,
    )

    return {
        "data": recipes,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "has_more": len(recipes) == limit,
        },
    }


# ── Meal Plans ───────────────────────────────────────────────────────────────

class MealPlanCreateRequest(BaseModel):
    name: str = "Weekly Meal Plan"
    start_date: date
    days: int = Field(7, ge=1, le=28, description="Plan duration in days")
    daily_calories: int | None = Field(None, ge=800, le=5000)
    daily_protein_g: float | None = Field(None, ge=0, le=500)
    daily_carbs_g: float | None = Field(None, ge=0, le=800)
    daily_fat_g: float | None = Field(None, ge=0, le=300)


class MealEntryRequest(BaseModel):
    recipe_id: str
    day_index: int = Field(..., ge=0, le=27)
    meal_type: str = Field(..., pattern="^(breakfast|lunch|dinner|snack)$")
    servings: float = Field(1.0, ge=0.25, le=10)
    notes: str | None = None


class AutoFillRequest(BaseModel):
    meal_types: list[str] = Field(
        default=["breakfast", "lunch", "dinner"],
        description="Which meals to auto-fill",
    )
    respect_targets: bool = Field(True, description="Try to hit daily macro targets")


@router.post("/users/{user_id}/meal-plans", status_code=201)
async def create_meal_plan(
    user_id: str,
    req: MealPlanCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new meal plan with daily nutritional targets."""
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    end_date = req.start_date + timedelta(days=req.days - 1)

    plan = MealPlanRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=req.name,
        start_date=req.start_date,
        end_date=end_date,
        daily_calories=req.daily_calories,
        daily_protein_g=req.daily_protein_g,
        daily_carbs_g=req.daily_carbs_g,
        daily_fat_g=req.daily_fat_g,
    )
    session.add(plan)
    await session.commit()

    return {
        "id": plan.id,
        "name": plan.name,
        "start_date": str(plan.start_date),
        "end_date": str(plan.end_date),
        "daily_targets": {
            "calories": plan.daily_calories,
            "protein_g": plan.daily_protein_g,
            "carbs_g": plan.daily_carbs_g,
            "fat_g": plan.daily_fat_g,
        },
        "days": req.days,
        "entries": [],
    }


@router.get("/users/{user_id}/meal-plans")
async def list_meal_plans(
    user_id: str,
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """List user's meal plans, most recent first."""
    plans = (await session.execute(
        select(MealPlanRow)
        .where(MealPlanRow.user_id == user_id)
        .order_by(MealPlanRow.start_date.desc())
        .limit(limit)
    )).scalars().all()

    return {
        "data": [
            {
                "id": p.id,
                "name": p.name,
                "start_date": str(p.start_date),
                "end_date": str(p.end_date),
                "daily_targets": {
                    "calories": p.daily_calories,
                    "protein_g": p.daily_protein_g,
                },
            }
            for p in plans
        ]
    }


@router.get("/users/{user_id}/meal-plans/{plan_id}")
async def get_meal_plan(
    user_id: str,
    plan_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a meal plan with all entries and daily macro summaries."""
    plan = (await session.execute(
        select(MealPlanRow).where(
            MealPlanRow.id == plan_id,
            MealPlanRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Meal plan not found")

    # Fetch entries with recipe data
    entries = (await session.execute(
        select(MealPlanEntryRow, RecipeRow)
        .outerjoin(RecipeRow, MealPlanEntryRow.recipe_id == RecipeRow.id)
        .where(MealPlanEntryRow.plan_id == plan_id)
        .order_by(MealPlanEntryRow.day_index, MealPlanEntryRow.meal_type)
    )).all()

    # Organize by day
    num_days = (plan.end_date - plan.start_date).days + 1
    days: list[dict] = []
    for d in range(num_days):
        day_entries = []
        day_cals = 0.0
        day_protein = 0.0
        day_carbs = 0.0
        day_fat = 0.0

        for entry, recipe in entries:
            if entry.day_index != d:
                continue
            servings = entry.servings or 1.0
            cals = (recipe.calories or 0) * servings if recipe else 0
            prot = (recipe.protein_g or 0) * servings if recipe else 0
            carbs = (recipe.carbs_g or 0) * servings if recipe else 0
            fat = (recipe.fat_g or 0) * servings if recipe else 0

            day_cals += cals
            day_protein += prot
            day_carbs += carbs
            day_fat += fat

            day_entries.append({
                "id": entry.id,
                "meal_type": entry.meal_type,
                "servings": servings,
                "notes": entry.notes,
                "recipe": {
                    "id": recipe.id,
                    "title": recipe.title,
                    "thumbnail_url": recipe.thumbnail_url,
                    "calories": recipe.calories,
                    "protein_g": recipe.protein_g,
                    "cook_time_minutes": recipe.cook_time_minutes,
                } if recipe else None,
            })

        target_cals = plan.daily_calories
        days.append({
            "day_index": d,
            "date": str(plan.start_date + timedelta(days=d)),
            "entries": day_entries,
            "totals": {
                "calories": round(day_cals),
                "protein_g": round(day_protein, 1),
                "carbs_g": round(day_carbs, 1),
                "fat_g": round(day_fat, 1),
            },
            "targets_met": {
                "calories": day_cals <= (target_cals or 99999),
                "protein": day_protein >= (plan.daily_protein_g or 0),
            },
        })

    return {
        "id": plan.id,
        "name": plan.name,
        "start_date": str(plan.start_date),
        "end_date": str(plan.end_date),
        "daily_targets": {
            "calories": plan.daily_calories,
            "protein_g": plan.daily_protein_g,
            "carbs_g": plan.daily_carbs_g,
            "fat_g": plan.daily_fat_g,
        },
        "days": days,
    }


@router.post("/users/{user_id}/meal-plans/{plan_id}/entries", status_code=201)
async def add_meal_entry(
    user_id: str,
    plan_id: str,
    req: MealEntryRequest,
    session: AsyncSession = Depends(get_session),
):
    """Add a recipe to a specific meal slot in the plan."""
    plan = (await session.execute(
        select(MealPlanRow).where(
            MealPlanRow.id == plan_id,
            MealPlanRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Meal plan not found")

    num_days = (plan.end_date - plan.start_date).days + 1
    if req.day_index >= num_days:
        raise HTTPException(400, f"day_index must be 0-{num_days - 1}")

    # Verify recipe exists
    recipe = (await session.execute(
        select(RecipeRow).where(RecipeRow.id == req.recipe_id)
    )).scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    # Check for duplicate slot
    existing = (await session.execute(
        select(MealPlanEntryRow).where(
            MealPlanEntryRow.plan_id == plan_id,
            MealPlanEntryRow.day_index == req.day_index,
            MealPlanEntryRow.meal_type == req.meal_type,
            MealPlanEntryRow.recipe_id == req.recipe_id,
        )
    )).scalar_one_or_none()
    if existing:
        # Update servings/notes
        existing.servings = req.servings
        existing.notes = req.notes
        await session.commit()
        return {"status": "updated", "entry_id": existing.id}

    entry = MealPlanEntryRow(
        id=str(uuid.uuid4()),
        plan_id=plan_id,
        recipe_id=req.recipe_id,
        day_index=req.day_index,
        meal_type=req.meal_type,
        servings=req.servings,
        notes=req.notes,
    )
    session.add(entry)
    await session.commit()

    return {
        "status": "added",
        "entry_id": entry.id,
        "recipe": {
            "id": recipe.id,
            "title": recipe.title,
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
        },
    }


@router.delete("/users/{user_id}/meal-plans/{plan_id}/entries/{entry_id}", status_code=204)
async def remove_meal_entry(
    user_id: str,
    plan_id: str,
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a recipe from a meal plan slot."""
    # Verify ownership
    plan = (await session.execute(
        select(MealPlanRow).where(
            MealPlanRow.id == plan_id,
            MealPlanRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Meal plan not found")

    result = await session.execute(
        delete(MealPlanEntryRow).where(
            MealPlanEntryRow.id == entry_id,
            MealPlanEntryRow.plan_id == plan_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Entry not found")
    await session.commit()


@router.delete("/users/{user_id}/meal-plans/{plan_id}", status_code=204)
async def delete_meal_plan(
    user_id: str,
    plan_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a meal plan and all its entries."""
    result = await session.execute(
        delete(MealPlanRow).where(
            MealPlanRow.id == plan_id,
            MealPlanRow.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Meal plan not found")
    await session.commit()


@router.post("/users/{user_id}/meal-plans/{plan_id}/auto-fill")
async def auto_fill_meal_plan(
    user_id: str,
    plan_id: str,
    req: AutoFillRequest,
    session: AsyncSession = Depends(get_session),
):
    """Auto-fill empty meal slots with personalized recipe recommendations.

    Uses the recommendation engine to pick recipes that:
    - Match user dietary preferences
    - Hit daily macro targets when possible
    - Avoid repeating the same recipe in consecutive days
    """
    plan = (await session.execute(
        select(MealPlanRow).where(
            MealPlanRow.id == plan_id,
            MealPlanRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Meal plan not found")

    # Get existing entries
    existing = (await session.execute(
        select(MealPlanEntryRow).where(MealPlanEntryRow.plan_id == plan_id)
    )).scalars().all()
    filled_slots = {(e.day_index, e.meal_type) for e in existing}

    num_days = (plan.end_date - plan.start_date).days + 1

    # Get candidate recipes with user preferences
    feed = await get_personalized_feed(
        user_id=user_id,
        session=session,
        limit=100,
        offset=0,
        exclude_saved=False,
    )

    if not feed:
        return {"filled": 0, "message": "No recipes available to fill plan"}

    # Smart assignment: distribute recipes across empty slots
    target_cal_per_meal = {}
    if plan.daily_calories:
        # Rough split: breakfast 25%, lunch 35%, dinner 35%, snack 5%
        splits = {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.35, "snack": 0.05}
        target_cal_per_meal = {m: plan.daily_calories * s for m, s in splits.items()}

    added = 0
    used_recipe_ids: set[str] = set()
    recipe_idx = 0

    for day in range(num_days):
        for meal_type in req.meal_types:
            if (day, meal_type) in filled_slots:
                continue

            # Find best recipe for this slot
            best = _pick_recipe_for_slot(
                feed, target_cal_per_meal.get(meal_type), used_recipe_ids, recipe_idx
            )
            if not best:
                continue

            entry = MealPlanEntryRow(
                id=str(uuid.uuid4()),
                plan_id=plan_id,
                recipe_id=best["id"],
                day_index=day,
                meal_type=meal_type,
                servings=1.0,
            )
            session.add(entry)
            used_recipe_ids.add(best["id"])
            added += 1
            recipe_idx += 1

    await session.commit()

    return {
        "filled": added,
        "total_slots": num_days * len(req.meal_types),
        "message": f"Added {added} recipes to your meal plan",
    }


def _pick_recipe_for_slot(
    feed: list[dict],
    target_calories: float | None,
    used_ids: set[str],
    offset: int,
) -> dict | None:
    """Pick the best available recipe for a meal slot."""
    # Prefer unused recipes, but allow repeats if needed
    candidates = [r for r in feed if r["id"] not in used_ids]
    if not candidates:
        candidates = feed

    if not candidates:
        return None

    if target_calories and target_calories > 0:
        # Sort by calorie closeness to target
        def cal_distance(r: dict) -> float:
            cals = (r.get("nutrition") or {}).get("calories")
            if cals is None:
                return 999
            return abs(cals - target_calories)
        candidates.sort(key=cal_distance)
        return candidates[0]

    # Default: use relevance score ordering with offset for variety
    idx = offset % len(candidates)
    return candidates[idx]
