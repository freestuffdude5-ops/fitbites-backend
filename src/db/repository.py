"""Recipe repository — DB CRUD operations + Pydantic conversion."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.tables import RecipeRow
from src.models import Recipe, Creator, NutritionInfo, Ingredient, Platform


def _escape_like(value: str) -> str:
    """Escape LIKE wildcard characters in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_recipe(row: RecipeRow) -> Recipe:
    """Convert a DB row to a Pydantic Recipe."""
    nutrition = None
    if row.calories is not None:
        nutrition = NutritionInfo(
            calories=row.calories,
            protein_g=row.protein_g or 0,
            carbs_g=row.carbs_g or 0,
            fat_g=row.fat_g or 0,
            fiber_g=row.fiber_g,
            sugar_g=row.sugar_g,
            servings=row.servings or 1,
        )

    ingredients = [Ingredient(**i) for i in (row.ingredients or [])]

    return Recipe(
        id=row.id,
        title=row.title,
        description=row.description,
        creator=Creator(
            username=row.creator_username,
            display_name=row.creator_display_name,
            platform=row.creator_platform,
            profile_url=row.creator_profile_url,
            avatar_url=row.creator_avatar_url,
            follower_count=row.creator_follower_count,
        ),
        platform=row.platform,
        source_url=row.source_url,
        thumbnail_url=row.thumbnail_url,
        video_url=row.video_url,
        ingredients=ingredients,
        steps=row.steps or [],
        nutrition=nutrition,
        views=row.views,
        likes=row.likes,
        comments=row.comments,
        shares=row.shares,
        tags=row.tags or [],
        cook_time_minutes=row.cook_time_minutes,
        difficulty=row.difficulty,
        virality_score=row.virality_score,
        scraped_at=row.scraped_at or datetime.now(tz=timezone.utc),
        published_at=row.published_at,
    )


def _recipe_to_row(recipe: Recipe) -> RecipeRow:
    """Convert a Pydantic Recipe to a DB row."""
    return RecipeRow(
        id=recipe.id,
        title=recipe.title,
        description=recipe.description,
        creator_username=recipe.creator.username,
        creator_display_name=recipe.creator.display_name,
        creator_platform=recipe.creator.platform,
        creator_profile_url=recipe.creator.profile_url,
        creator_avatar_url=recipe.creator.avatar_url,
        creator_follower_count=recipe.creator.follower_count,
        platform=recipe.platform,
        source_url=recipe.source_url,
        thumbnail_url=recipe.thumbnail_url,
        video_url=recipe.video_url,
        ingredients=[i.model_dump() for i in recipe.ingredients],
        steps=recipe.steps,
        tags=recipe.tags,
        calories=recipe.nutrition.calories if recipe.nutrition else None,
        protein_g=recipe.nutrition.protein_g if recipe.nutrition else None,
        carbs_g=recipe.nutrition.carbs_g if recipe.nutrition else None,
        fat_g=recipe.nutrition.fat_g if recipe.nutrition else None,
        fiber_g=recipe.nutrition.fiber_g if recipe.nutrition else None,
        sugar_g=recipe.nutrition.sugar_g if recipe.nutrition else None,
        servings=recipe.nutrition.servings if recipe.nutrition else 1,
        views=recipe.views,
        likes=recipe.likes,
        comments=recipe.comments,
        shares=recipe.shares,
        cook_time_minutes=recipe.cook_time_minutes,
        difficulty=recipe.difficulty,
        virality_score=recipe.virality_score,
        scraped_at=recipe.scraped_at,
        published_at=recipe.published_at,
    )


class RecipeRepository:
    """Async recipe CRUD backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, recipe: Recipe) -> Recipe:
        """Insert or update a recipe (keyed on source_url)."""
        stmt = select(RecipeRow).where(RecipeRow.source_url == recipe.source_url)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update fields
            row = _recipe_to_row(recipe)
            for col in RecipeRow.__table__.columns:
                if col.name != "id":
                    setattr(existing, col.name, getattr(row, col.name))
            await self.session.flush()
            return _row_to_recipe(existing)
        else:
            row = _recipe_to_row(recipe)
            self.session.add(row)
            await self.session.flush()
            return _row_to_recipe(row)

    async def get_by_id(self, recipe_id: str) -> Optional[Recipe]:
        stmt = select(RecipeRow).where(RecipeRow.id == recipe_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return _row_to_recipe(row) if row else None

    async def list_recipes(
        self,
        tag: str | None = None,
        platform: Platform | None = None,
        max_calories: int | None = None,
        min_protein: float | None = None,
        sort: str = "virality",
        limit: int = 20,
        offset: int = 0,
    ) -> list[Recipe]:
        stmt = select(RecipeRow)

        if tag:
            # JSON array contains — works for SQLite and Postgres
            stmt = stmt.where(RecipeRow.tags.contains(tag))
        if platform:
            stmt = stmt.where(RecipeRow.platform == platform)
        if max_calories is not None:
            stmt = stmt.where(RecipeRow.calories <= max_calories)
        if min_protein is not None:
            stmt = stmt.where(RecipeRow.protein_g >= min_protein)

        order_map = {
            "virality": RecipeRow.virality_score.desc(),
            "newest": RecipeRow.scraped_at.desc(),
            "calories": RecipeRow.calories.asc(),
            "protein": RecipeRow.protein_g.desc(),
        }
        stmt = stmt.order_by(order_map.get(sort, RecipeRow.virality_score.desc()))
        stmt = stmt.offset(offset).limit(limit)

        result = await self.session.execute(stmt)
        return [_row_to_recipe(r) for r in result.scalars().all()]

    async def search(self, query: str, limit: int = 20, offset: int = 0) -> list[Recipe]:
        escaped = _escape_like(query)
        q = f"%{escaped}%"
        stmt = (
            select(RecipeRow)
            .where(or_(RecipeRow.title.ilike(q), RecipeRow.description.ilike(q)))
            .order_by(RecipeRow.virality_score.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_row_to_recipe(r) for r in result.scalars().all()]

    async def search_count(self, query: str) -> int:
        escaped = _escape_like(query)
        q = f"%{escaped}%"
        stmt = select(func.count(RecipeRow.id)).where(
            or_(RecipeRow.title.ilike(q), RecipeRow.description.ilike(q))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(RecipeRow.id)))
        return result.scalar_one()
