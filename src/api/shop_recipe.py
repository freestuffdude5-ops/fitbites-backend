"""Shop Recipe API — One-tap grocery shopping with affiliate links."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.auth import get_current_user
from src.db.user_tables import UserRow
from src.services.affiliate import enrich_recipe, get_shop_all_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shop-recipe", tags=["shop"])


# ── Models ───────────────────────────────────────────────────────────────────


class IngredientWithLinks(BaseModel):
    name: str
    amount: str | None = None
    unit: str | None = None
    affiliate_links: dict[str, str]  # {"amazon": "https://...", "walmart": "https://..."}


class ShopRecipeResponse(BaseModel):
    recipe_id: str
    recipe_name: str
    ingredients: list[IngredientWithLinks]
    shop_all_url: str  # Amazon multi-item cart link
    providers_available: list[str]  # ["amazon", "walmart", "instacart"]


class TrackClickRequest(BaseModel):
    provider: str  # "amazon", "walmart", etc.
    ingredient_name: str | None = None  # Optional: which ingredient link was clicked


# ── Get Shop Recipe ──────────────────────────────────────────────────────────


@router.get("/{recipe_id}", response_model=ShopRecipeResponse)
async def get_shop_recipe(
    recipe_id: str,
    user_id: str = Query(None, description="Optional user ID for click tracking"),
    session: AsyncSession = Depends(get_session),
):
    """Get all recipe ingredients with affiliate links from multiple providers."""
    # Fetch recipe
    result = await session.execute(
        select(RecipeRow).where(RecipeRow.id == recipe_id)
    )
    recipe = result.scalar_one_or_none()
    
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    
    # Enrich with affiliate links
    enriched = enrich_recipe(recipe)
    
    # Build ingredient list with affiliate links
    ingredients_with_links = []
    for ing in enriched.get("ingredients", []):
        # Extract affiliate links from ingredient metadata
        affiliate_links = {}
        if "amazon_url" in ing:
            affiliate_links["amazon"] = ing["amazon_url"]
        if "walmart_url" in ing:
            affiliate_links["walmart"] = ing["walmart_url"]
        if "instacart_url" in ing:
            affiliate_links["instacart"] = ing["instacart_url"]
        
        ingredients_with_links.append(
            IngredientWithLinks(
                name=ing.get("name", ""),
                amount=ing.get("amount"),
                unit=ing.get("unit"),
                affiliate_links=affiliate_links,
            )
        )
    
    # Generate "Shop All" URL (Amazon multi-item cart)
    shop_all_url = get_shop_all_url(enriched.get("ingredients", []))
    
    # List available providers
    providers = set()
    for ing in ingredients_with_links:
        providers.update(ing.affiliate_links.keys())
    
    return ShopRecipeResponse(
        recipe_id=recipe_id,
        recipe_name=recipe.name,
        ingredients=ingredients_with_links,
        shop_all_url=shop_all_url,
        providers_available=sorted(list(providers)),
    )


# ── Track Click ──────────────────────────────────────────────────────────────


@router.post("/{recipe_id}/track-click")
async def track_shop_click(
    recipe_id: str,
    request: TrackClickRequest,
    user: UserRow = Depends(get_current_user),  # Optional auth
    session: AsyncSession = Depends(get_session),
):
    """Track affiliate link clicks for revenue attribution."""
    # TODO: Implement click tracking (store in analytics DB)
    # For now, just log it
    logger.info(
        f"Shop click tracked: recipe={recipe_id} provider={request.provider} "
        f"ingredient={request.ingredient_name} user={user.id if user else 'anonymous'}"
    )
    
    return {
        "success": True,
        "message": "Click tracked",
        "recipe_id": recipe_id,
        "provider": request.provider,
    }
