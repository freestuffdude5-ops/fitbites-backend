"""Smart recipe recommendation engine.

Personalizes the feed based on:
1. User dietary preferences (keto, gluten-free, calorie caps, protein floors)
2. Saved recipe history (favor similar tags, platforms, macro profiles)
3. Virality score (baseline quality signal)
4. Freshness boost (newer recipes get a bump)
5. Diversity penalty (avoid showing too many similar recipes in a row)

No ML needed — smart scoring + SQL filtering delivers a premium feel.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from collections import Counter

from sqlalchemy import select, func, not_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.tables import RecipeRow
from src.db.user_tables import UserRow, SavedRecipeRow


async def get_personalized_feed(
    user_id: str,
    session: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    exclude_saved: bool = True,
) -> list[dict]:
    """Return a personalized recipe feed for a user.

    Scoring formula per recipe:
        score = virality_base
              + preference_match_bonus
              + tag_affinity_bonus
              + freshness_boost
              - diversity_penalty
    """
    # 1. Load user preferences
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()

    prefs = (user.preferences or {}) if user else {}
    dietary = set(prefs.get("dietary", []))
    max_cal = prefs.get("max_calories")
    min_prot = prefs.get("min_protein")
    excluded_ings = set(prefs.get("excluded_ingredients", []))

    # 2. Build user taste profile from saved recipes
    tag_affinity: Counter = Counter()
    platform_affinity: Counter = Counter()
    saved_ids: set[str] = set()

    if user:
        saved_rows = (await session.execute(
            select(SavedRecipeRow.recipe_id).where(SavedRecipeRow.user_id == user_id)
        )).scalars().all()
        saved_ids = set(saved_rows)

        if saved_ids:
            saved_recipes = (await session.execute(
                select(RecipeRow).where(RecipeRow.id.in_(list(saved_ids)[:100]))
            )).scalars().all()
            for r in saved_recipes:
                for tag in (r.tags or []):
                    tag_affinity[tag] += 1
                if r.platform:
                    platform_affinity[r.platform] += 1

    # 3. Fetch candidate recipes with hard filters
    stmt = select(RecipeRow)

    if max_cal is not None:
        stmt = stmt.where((RecipeRow.calories <= max_cal) | (RecipeRow.calories.is_(None)))
    if min_prot is not None:
        stmt = stmt.where((RecipeRow.protein_g >= min_prot) | (RecipeRow.protein_g.is_(None)))
    if exclude_saved and saved_ids:
        stmt = stmt.where(not_(RecipeRow.id.in_(list(saved_ids))))

    # Fetch more than needed so we can re-rank
    fetch_limit = min(limit * 5, 200)
    stmt = stmt.order_by(RecipeRow.virality_score.desc().nullslast()).limit(fetch_limit)
    candidates = (await session.execute(stmt)).scalars().all()

    # 4. Score and rank
    now = datetime.now(timezone.utc)
    scored: list[tuple[float, RecipeRow]] = []

    for recipe in candidates:
        score = _score_recipe(recipe, tag_affinity, platform_affinity, dietary, excluded_ings, now)
        scored.append((score, recipe))

    # 5. Diversity pass — penalize consecutive recipes with same dominant tag
    scored.sort(key=lambda x: x[0], reverse=True)
    diversified = _diversify(scored, limit + offset)

    # 6. Slice for pagination
    page = diversified[offset:offset + limit]

    return [_recipe_to_feed_item(recipe, score) for score, recipe in page]


def _score_recipe(
    recipe: RecipeRow,
    tag_affinity: Counter,
    platform_affinity: Counter,
    dietary_prefs: set[str],
    excluded_ings: set[str],
    now: datetime,
) -> float:
    """Compute a personalized relevance score for a recipe."""
    # Base: virality (0-100 scale)
    score = (recipe.virality_score or 0) * 0.4

    # Tag affinity: recipes matching user's favorite tags get boosted
    recipe_tags = set(recipe.tags or [])
    if tag_affinity:
        max_tag_freq = max(tag_affinity.values()) if tag_affinity else 1
        tag_boost = sum(tag_affinity.get(t, 0) / max_tag_freq for t in recipe_tags)
        score += min(tag_boost * 15, 30)  # Cap at 30 points

    # Dietary match: recipes matching stated preferences get a bonus
    if dietary_prefs and recipe_tags:
        diet_overlap = len(dietary_prefs & recipe_tags)
        score += diet_overlap * 10

    # Platform affinity
    if recipe.platform and platform_affinity:
        max_plat = max(platform_affinity.values())
        plat_boost = platform_affinity.get(recipe.platform, 0) / max_plat
        score += plat_boost * 5

    # Freshness boost: recipes from last 7 days get up to 10 points
    if recipe.scraped_at:
        scraped = recipe.scraped_at
        if scraped.tzinfo is None:
            scraped = scraped.replace(tzinfo=timezone.utc)
        age_hours = (now - scraped).total_seconds() / 3600
        freshness = max(0, 10 - (age_hours / 168) * 10)  # 168h = 7 days
        score += freshness

    # Macro quality bonus: high protein, low calorie recipes get a nudge
    if recipe.protein_g and recipe.calories and recipe.calories > 0:
        protein_ratio = recipe.protein_g / (recipe.calories / 100)  # g protein per 100 cal
        score += min(protein_ratio * 2, 8)

    # Penalty: exclude recipes with unwanted ingredients
    if excluded_ings and recipe.ingredients:
        for ing in recipe.ingredients:
            name = (ing.get("name") or "").lower()
            if any(ex.lower() in name for ex in excluded_ings):
                score -= 50  # Heavy penalty
                break

    return round(score, 2)


def _diversify(scored: list[tuple[float, RecipeRow]], target: int) -> list[tuple[float, RecipeRow]]:
    """Re-order to avoid consecutive recipes with the same primary tag."""
    if len(scored) <= 2:
        return scored

    result: list[tuple[float, RecipeRow]] = []
    remaining = list(scored)
    last_tags: list[str] = []

    while remaining and len(result) < target:
        best_idx = 0
        best_penalty = 0.0

        for i, (score, recipe) in enumerate(remaining[:30]):  # Only scan top 30 for perf
            tags = recipe.tags or []
            primary_tag = tags[0] if tags else ""
            penalty = 0.0
            if primary_tag and primary_tag in last_tags[-2:]:
                penalty = 5.0  # Penalize repeats in last 2 slots
            adjusted = score - penalty
            if i == 0 or adjusted > (remaining[best_idx][0] - best_penalty):
                best_idx = i
                best_penalty = penalty

        chosen_score, chosen_recipe = remaining.pop(best_idx)
        result.append((chosen_score, chosen_recipe))
        tags = chosen_recipe.tags or []
        last_tags.append(tags[0] if tags else "")

    return result


def _recipe_to_feed_item(recipe: RecipeRow, score: float) -> dict:
    """Convert to a rich feed item suitable for the iOS client."""
    return {
        "id": recipe.id,
        "title": recipe.title,
        "description": recipe.description,
        "thumbnail_url": recipe.thumbnail_url,
        "video_url": recipe.video_url,
        "platform": recipe.platform.value if recipe.platform else None,
        "creator": {
            "username": recipe.creator_username,
            "display_name": recipe.creator_display_name,
            "avatar_url": recipe.creator_avatar_url,
        },
        "nutrition": {
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
            "carbs_g": recipe.carbs_g,
            "fat_g": recipe.fat_g,
        } if recipe.calories is not None else None,
        "cook_time_minutes": recipe.cook_time_minutes,
        "difficulty": recipe.difficulty,
        "tags": recipe.tags or [],
        "virality_score": recipe.virality_score,
        "relevance_score": score,
        "ingredient_count": len(recipe.ingredients or []),
    }
