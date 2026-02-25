"""Advanced search & filter API — premium search experience."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/discover")
async def discover_recipes(
    q: str | None = Query(None, description="Search query (title/description)"),
    tags: str | None = Query(None, description="Comma-separated tags (e.g. high-protein,keto)"),
    min_calories: int | None = Query(None, ge=0),
    max_calories: int | None = Query(None, ge=0),
    min_protein: float | None = Query(None, ge=0),
    max_protein: float | None = Query(None, ge=0),
    min_carbs: float | None = Query(None, ge=0),
    max_carbs: float | None = Query(None, ge=0),
    min_fat: float | None = Query(None, ge=0),
    max_fat: float | None = Query(None, ge=0),
    max_cook_time: int | None = Query(None, ge=0, description="Max cook time in minutes"),
    difficulty: str | None = Query(None, description="easy, medium, or hard"),
    platform: str | None = Query(None, description="youtube or reddit"),
    min_rating: float | None = Query(None, ge=0, le=5),
    sort: str = Query(
        "relevance",
        description="Sort: relevance, virality, newest, calories_asc, calories_desc, protein_desc, cook_time_asc",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Advanced recipe discovery with multi-dimensional filtering.

    Combines text search with macro filters, cook time, difficulty,
    and platform filtering. Supports multiple sort strategies.

    Premium UX: returns facet counts for active filters so the UI
    can show "23 high-protein recipes under 400 cal".
    """
    # Build base query
    stmt = select(RecipeRow)
    count_stmt = select(func.count()).select_from(RecipeRow)
    conditions = []

    # Text search
    if q:
        search_term = f"%{q.lower()}%"
        text_cond = or_(
            func.lower(RecipeRow.title).like(search_term),
            func.lower(RecipeRow.description).like(search_term),
        )
        conditions.append(text_cond)

    # Tag filtering
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            # JSON array contains check — works with SQLite JSON
            conditions.append(
                func.lower(cast(RecipeRow.tags, String)).like(f"%{tag}%")
            )

    # Macro filters
    if min_calories is not None:
        conditions.append(RecipeRow.calories >= min_calories)
    if max_calories is not None:
        conditions.append(RecipeRow.calories <= max_calories)
    if min_protein is not None:
        conditions.append(RecipeRow.protein_g >= min_protein)
    if max_protein is not None:
        conditions.append(RecipeRow.protein_g <= max_protein)
    if min_carbs is not None:
        conditions.append(RecipeRow.carbs_g >= min_carbs)
    if max_carbs is not None:
        conditions.append(RecipeRow.carbs_g <= max_carbs)
    if min_fat is not None:
        conditions.append(RecipeRow.fat_g >= min_fat)
    if max_fat is not None:
        conditions.append(RecipeRow.fat_g <= max_fat)

    # Cook time
    if max_cook_time is not None:
        conditions.append(RecipeRow.cook_time_minutes <= max_cook_time)

    # Difficulty
    if difficulty:
        conditions.append(func.lower(RecipeRow.difficulty) == difficulty.lower())

    # Platform
    if platform:
        conditions.append(func.lower(cast(RecipeRow.platform, String)) == platform.lower())

    # Apply conditions
    if conditions:
        combined = and_(*conditions)
        stmt = stmt.where(combined)
        count_stmt = count_stmt.where(combined)

    # Sorting
    sort_map = {
        "relevance": RecipeRow.virality_score.desc().nullslast(),
        "virality": RecipeRow.virality_score.desc().nullslast(),
        "newest": RecipeRow.scraped_at.desc().nullslast(),
        "calories_asc": RecipeRow.calories.asc().nullslast(),
        "calories_desc": RecipeRow.calories.desc().nullslast(),
        "protein_desc": RecipeRow.protein_g.desc().nullslast(),
        "cook_time_asc": RecipeRow.cook_time_minutes.asc().nullslast(),
    }
    order = sort_map.get(sort, sort_map["relevance"])
    stmt = stmt.order_by(order).limit(limit).offset(offset)

    # Execute
    result = await session.execute(stmt)
    rows = result.scalars().all()
    total = (await session.execute(count_stmt)).scalar() or 0

    from src.db.repository import _row_to_recipe
    recipes = [_row_to_recipe(r) for r in rows]

    # Build facet summary
    facets = {
        "total_results": total,
        "filters_applied": sum([
            q is not None,
            tags is not None,
            min_calories is not None or max_calories is not None,
            min_protein is not None or max_protein is not None,
            max_cook_time is not None,
            difficulty is not None,
            platform is not None,
        ]),
    }

    return {
        "data": recipes,
        "facets": facets,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }


@router.get("/discover/quick-filters")
async def quick_filters(
    session: AsyncSession = Depends(get_session),
):
    """Pre-built filter shortcuts for the explore screen.

    Returns curated filter combos like "High Protein Under 400cal"
    with result counts so the UI can show popular filter pills.
    """
    filters = [
        {
            "label": "High Protein",
            "icon": "💪",
            "params": {"min_protein": 30, "sort": "protein_desc"},
        },
        {
            "label": "Under 300 Cal",
            "icon": "🔥",
            "params": {"max_calories": 300, "sort": "calories_asc"},
        },
        {
            "label": "Quick Meals",
            "icon": "⚡",
            "params": {"max_cook_time": 15, "sort": "virality"},
        },
        {
            "label": "Keto Friendly",
            "icon": "🥑",
            "params": {"tags": "keto", "max_carbs": 20, "sort": "virality"},
        },
        {
            "label": "Meal Prep",
            "icon": "📦",
            "params": {"tags": "meal-prep", "sort": "virality"},
        },
        {
            "label": "High Protein + Low Cal",
            "icon": "🎯",
            "params": {"min_protein": 25, "max_calories": 400, "sort": "protein_desc"},
        },
        {
            "label": "Easy Recipes",
            "icon": "👶",
            "params": {"difficulty": "easy", "sort": "virality"},
        },
        {
            "label": "Trending Now",
            "icon": "📈",
            "params": {"sort": "virality"},
        },
    ]

    # Get counts for each filter
    for f in filters:
        conditions = []
        p = f["params"]
        if p.get("min_protein"):
            conditions.append(RecipeRow.protein_g >= p["min_protein"])
        if p.get("max_calories"):
            conditions.append(RecipeRow.calories <= p["max_calories"])
        if p.get("max_cook_time"):
            conditions.append(RecipeRow.cook_time_minutes <= p["max_cook_time"])
        if p.get("max_carbs"):
            conditions.append(RecipeRow.carbs_g <= p["max_carbs"])
        if p.get("difficulty"):
            conditions.append(func.lower(RecipeRow.difficulty) == p["difficulty"])
        if p.get("tags"):
            conditions.append(
                func.lower(cast(RecipeRow.tags, String)).like(f"%{p['tags']}%")
            )

        count_stmt = select(func.count()).select_from(RecipeRow)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        count = (await session.execute(count_stmt)).scalar() or 0
        f["count"] = count

    return {"filters": filters}
