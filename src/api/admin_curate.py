"""Admin endpoints for manual recipe curation."""
import uuid
import re
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, HttpUrl, field_validator
from datetime import datetime, timezone
import random

from src.db.engine import get_session
from src.db.tables import RecipeRow
from config.settings import settings

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class NutritionInput(BaseModel):
    """Nutrition facts for a recipe."""
    calories: int = Field(ge=0, description="Total calories per serving")
    protein_g: float = Field(ge=0, alias="protein", description="Protein in grams")
    carbs_g: float = Field(ge=0, default=0, alias="carbs", description="Carbs in grams")
    fat_g: float = Field(ge=0, default=0, alias="fat", description="Fat in grams")

    model_config = {"populate_by_name": True}


class RecipeCurationRequest(BaseModel):
    """Manual recipe curation request."""
    title: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl
    ingredients: list[str] = Field(min_length=1)
    nutrition: NutritionInput
    servings: int = Field(ge=1, default=1)
    steps: list[str] | None = None
    tags: list[str] | None = None
    description: str | None = Field(None, max_length=1000)

    @field_validator("source_url")
    @classmethod
    def validate_platform(cls, v: HttpUrl) -> HttpUrl:
        """Ensure URL is from supported platform."""
        url_str = str(v).lower()
        supported = ["instagram.com", "tiktok.com", "youtube.com", "youtu.be"]
        if not any(platform in url_str for platform in supported):
            raise ValueError(f"URL must be from Instagram, TikTok, or YouTube")
        return v

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str]) -> list[str]:
        """Ensure ingredients are non-empty."""
        cleaned = [ing.strip() for ing in v if ing.strip()]
        if not cleaned:
            raise ValueError("At least one ingredient is required")
        return cleaned


def verify_admin_key(x_admin_key: str = Header(None, alias="X-Admin-Key")) -> None:
    """Verify admin API key."""
    import hmac
    expected_key = settings.ADMIN_API_KEY
    if not expected_key:
        raise HTTPException(503, "Admin endpoints disabled")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected_key):
        raise HTTPException(403, "Invalid admin key")


def _detect_platform(url: str) -> str:
    """Detect platform from URL."""
    url_lower = url.lower()
    if "instagram.com" in url_lower:
        return "instagram"
    elif "tiktok.com" in url_lower:
        return "tiktok"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return "unknown"


def _add_affiliate_tags(ingredients: list[str]) -> list[str]:
    """Add Amazon affiliate tags to product links."""
    affiliate_tag = getattr(settings, 'AMAZON_ASSOCIATE_TAG', '83apps01-20')
    processed = []
    
    for ing in ingredients:
        if "amazon.com" in ing.lower():
            ing = re.sub(r'[?&]tag=[^&\s]+', '', ing)
            if '?' in ing:
                ing += f"&tag={affiliate_tag}"
            else:
                ing += f"?tag={affiliate_tag}"
        processed.append(ing)
    
    return processed


@router.get("/curate", response_class=HTMLResponse)
async def curate_form():
    """Serve manual recipe curation web form."""
    template_path = Path(__file__).parent.parent / "templates" / "curate.html"
    
    if not template_path.exists():
        raise HTTPException(404, "Curation form not found")
    
    return HTMLResponse(content=template_path.read_text())


@router.post("/recipes/curate")
async def curate_recipe(
    request: RecipeCurationRequest,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """
    Manually curate a recipe from social media.
    
    Requires: X-Admin-Key header with valid admin API key.
    
    Target: <60 seconds from URL to saved recipe.
    """
    # Detect platform
    source_platform = _detect_platform(str(request.source_url))
    
    # Process ingredients (add affiliate tags)
    processed_ingredients = _add_affiliate_tags(request.ingredients)
    
    # Normalize tags
    tags = request.tags or []
    if source_platform not in tags:
        tags.append(source_platform)
    
    # Create Recipe row
    now = datetime.now(timezone.utc)
    recipe = RecipeRow(
        id=str(uuid.uuid4()),
        title=request.title,
        description=request.description or f"Delicious recipe from {source_platform}",
        source_platform=source_platform,
        source_url=str(request.source_url),
        source_author="Manual Curation",
        creator_username="fitbites_curator",
        creator_profile_url=str(request.source_url),
        platform=source_platform,
        thumbnail_url=None,
        video_url=None,
        content_hash=None,
        ingredients=processed_ingredients,
        steps=request.steps or [],
        tags=tags,
        calories=request.nutrition.calories,
        protein_g=request.nutrition.protein_g,
        carbs_g=request.nutrition.carbs_g,
        fat_g=request.nutrition.fat_g,
        servings=request.servings,
        cook_time_minutes=None,
        views=0,
        likes=0,
        comments=0,
        shares=0,
        virality_score=50.0,
        scraped_at=now,
        published_at=now,
    )
    
    session.add(recipe)
    
    try:
        await session.commit()
        await session.refresh(recipe)
    except Exception as e:
        await session.rollback()
        if "unique" in str(e).lower() and "source_url" in str(e).lower():
            raise HTTPException(409, f"Recipe with this URL already exists")
        raise HTTPException(500, f"Failed to save recipe: {str(e)}")
    
    return {
        "success": True,
        "recipe_id": recipe.id,
        "message": f"Recipe '{recipe.title}' successfully curated!",
        "recipe": {
            "id": recipe.id,
            "title": recipe.title,
            "source_url": recipe.source_url,
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
        }
    }


@router.get("/recipes/stats")
async def get_recipe_stats(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """Get stats about curated recipes (admin only)."""
    from sqlalchemy import select, func
    
    # Total recipes
    total = (await session.execute(select(func.count()).select_from(RecipeRow))).scalar_one()
    
    # By platform
    platform_counts = {}
    platforms = (await session.execute(
        select(RecipeRow.source_platform, func.count()).group_by(RecipeRow.source_platform)
    )).all()
    
    for platform, count in platforms:
        platform_counts[platform] = count
    
    return {
        "total_recipes": total,
        "by_platform": platform_counts,
    }
