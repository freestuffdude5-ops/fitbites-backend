"""Recently Viewed API — Track and retrieve user's recipe browsing history."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_user
from src.db.engine import get_session
from src.db.recently_viewed_tables import RecentlyViewedRow
from src.db.user_tables import UserRow
from src.db.tables import RecipeRow

logger = logging.getLogger(__name__)
router = APIRouter()


class RecipePreview(BaseModel):
    """Recipe preview for history list."""
    id: str
    title: str
    image_url: str | None
    calories: int | None
    protein_g: int | None
    cook_time_minutes: int | None
    platform: str
    viewed_at: datetime


class RecentlyViewedResponse(BaseModel):
    """Recently viewed recipes list."""
    recipes: list[RecipePreview]
    total: int


@router.post("/api/v1/recipes/{recipe_id}/view", status_code=204)
async def track_view(
    recipe_id: str,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Track that user viewed a recipe (idempotent - updates timestamp if exists)."""
    # Verify recipe exists
    recipe = await session.get(RecipeRow, recipe_id)
    if not recipe:
        from fastapi import HTTPException
        raise HTTPException(404, "Recipe not found")
    
    # Check if already viewed
    result = await session.execute(
        select(RecentlyViewedRow).where(
            RecentlyViewedRow.user_id == user.id,
            RecentlyViewedRow.recipe_id == recipe_id,
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Update timestamp
        existing.viewed_at = datetime.now(timezone.utc)
    else:
        # Create new entry
        view = RecentlyViewedRow(user_id=user.id, recipe_id=recipe_id)
        session.add(view)
    
    await session.commit()
    logger.info(f"User {user.id} viewed recipe {recipe_id}")


@router.get("/api/v1/users/{user_id}/recently-viewed", response_model=RecentlyViewedResponse)
async def get_recently_viewed(
    user_id: str,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
):
    """Get user's recently viewed recipes."""
    if user.id != user_id:
        from fastapi import HTTPException
        raise HTTPException(403, "Cannot view other users' history")
    
    # Get recent views with recipe details
    query = (
        select(RecentlyViewedRow, RecipeRow)
        .join(RecipeRow, RecentlyViewedRow.recipe_id == RecipeRow.id)
        .where(RecentlyViewedRow.user_id == user_id)
        .order_by(RecentlyViewedRow.viewed_at.desc())
        .limit(limit)
    )
    
    result = await session.execute(query)
    rows = result.all()
    
    recipes = [
        RecipePreview(
            id=recipe.id,
            title=recipe.title,
            image_url=recipe.thumbnail_url,
            calories=recipe.calories,
            protein_g=recipe.protein_g,
            cook_time_minutes=recipe.cook_time_minutes,
            platform=recipe.platform,
            viewed_at=view.viewed_at,
        )
        for view, recipe in rows
    ]
    
    return RecentlyViewedResponse(recipes=recipes, total=len(recipes))


@router.delete("/api/v1/users/{user_id}/recently-viewed", status_code=204)
async def clear_history(
    user_id: str,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Clear user's recently viewed history."""
    if user.id != user_id:
        from fastapi import HTTPException
        raise HTTPException(403, "Cannot clear other users' history")
    
    await session.execute(
        delete(RecentlyViewedRow).where(RecentlyViewedRow.user_id == user_id)
    )
    await session.commit()
    logger.info(f"User {user_id} cleared recently viewed history")
