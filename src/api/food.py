"""Food Search API — /api/v1/food/* endpoints.

Provides food name search, common foods listing, and quick-log parsing
for the FitBites nutrition tracker.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.services.food_database import search_foods, get_common_foods, get_food_by_name, scale_nutrition
from src.services.food_parser import parse_food_entry, parse_multiple

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/food", tags=["food"])


@router.get("/search")
async def food_search(
    q: str = Query(..., min_length=1, max_length=200, description="Food name to search"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search food database by name.

    Returns matching foods with nutrition info per 100g.
    Supports fuzzy matching (e.g., "chiken" → "chicken breast").

    Example: GET /api/v1/food/search?q=chicken%20breast
    """
    results = search_foods(q, limit=limit)
    return {
        "query": q,
        "results": results,
        "count": len(results),
    }


@router.get("/common")
async def common_foods(
    limit: int = Query(100, ge=1, le=500),
    category: str | None = Query(None, description="Filter by category (protein, dairy, grains, vegetables, fruits, legumes, nuts, oils, other)"),
):
    """Get list of most common foods with nutrition data.

    Returns top foods sorted by category. All nutrition values are per 100g.

    Example: GET /api/v1/food/common?category=protein
    """
    foods = get_common_foods(limit=500)  # Get all, filter if needed
    if category:
        foods = [f for f in foods if f["category"] == category.lower()]
    foods = foods[:limit]
    categories = sorted(set(f["category"] for f in get_common_foods(500)))
    return {
        "foods": foods,
        "count": len(foods),
        "categories": categories,
    }


@router.get("/lookup/{food_name:path}")
async def food_lookup(food_name: str):
    """Look up a specific food by name.

    Returns exact match or closest match with full nutrition data per 100g.

    Example: GET /api/v1/food/lookup/chicken%20breast
    """
    food = get_food_by_name(food_name)
    if not food:
        raise HTTPException(404, f"Food not found: {food_name}")
    return food


class QuickLogRequest(BaseModel):
    text: str
    user_id: str | None = None

    model_config = {"json_schema_extra": {
        "examples": [
            {"text": "grilled chicken 200g", "user_id": "user_123"},
            {"text": "2 eggs and 1 cup rice"},
            {"text": "salmon 150g, broccoli 100g, brown rice 200g"},
        ]
    }}


class QuickLogResponse(BaseModel):
    original_text: str
    entries: list[dict]
    total_calories: int
    total_protein: float
    total_carbs: float
    total_fat: float
    total_fiber: float


@router.post("/quick-log", response_model=QuickLogResponse)
async def quick_log(req: QuickLogRequest):
    """Parse natural language food input and return structured nutrition data.

    Accepts free-text like "grilled chicken 200g" and returns parsed food
    with calculated nutrition. Supports multiple items separated by commas or 'and'.

    Supports:
    - Weight: "chicken 200g", "salmon 6oz"
    - Quantity: "2 eggs", "3 slices bread"
    - Volume: "1 cup rice", "2 tbsp olive oil"
    - Cooking methods: "grilled", "baked", "fried" (stripped for matching)
    - Multiple items: "chicken 200g, rice 150g and broccoli 100g"

    Example: POST /api/v1/food/quick-log
    Body: {"text": "grilled chicken breast 200g, brown rice 1 cup"}
    """
    parsed = parse_multiple(req.text)

    entries = [p.to_dict() for p in parsed]
    total_cal = sum(p.nutrition["calories"] for p in parsed if p.nutrition)
    total_pro = sum(p.nutrition["protein"] for p in parsed if p.nutrition)
    total_carb = sum(p.nutrition["carbs"] for p in parsed if p.nutrition)
    total_fat = sum(p.nutrition["fat"] for p in parsed if p.nutrition)
    total_fiber = sum(p.nutrition["fiber"] for p in parsed if p.nutrition)

    return QuickLogResponse(
        original_text=req.text,
        entries=entries,
        total_calories=total_cal,
        total_protein=round(total_pro, 1),
        total_carbs=round(total_carb, 1),
        total_fat=round(total_fat, 1),
        total_fiber=round(total_fiber, 1),
    )


@router.post("/calculate")
async def calculate_nutrition(
    food_name: str = Query(..., description="Food name"),
    amount_g: float = Query(..., gt=0, description="Amount in grams"),
):
    """Calculate nutrition for a specific food and amount.

    Example: POST /api/v1/food/calculate?food_name=chicken%20breast&amount_g=200
    """
    food = get_food_by_name(food_name)
    if not food:
        raise HTTPException(404, f"Food not found: {food_name}")
    return scale_nutrition(food, amount_g)
