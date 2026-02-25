"""Recipe Sharing API — generate shareable links, deep links, and Open Graph metadata."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.auth import get_current_user
from src.db.user_tables import UserRow

router = APIRouter(prefix="/api/v1", tags=["sharing"])


# ── Models ──────────────────────────────────────────────────────────────

class ShareLinkResponse(BaseModel):
    share_url: str
    recipe_id: str
    title: str
    description: str
    og_image_url: str | None = None


# ── Share link generation ───────────────────────────────────────────────

def _short_id(recipe_id: str) -> str:
    """Generate a short shareable ID from recipe ID."""
    return hashlib.sha256(recipe_id.encode()).hexdigest()[:8]


@router.get("/recipes/{recipe_id}/share")
async def get_share_link(
    recipe_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Generate a shareable link for a recipe. No auth required — enables viral sharing."""
    recipe = (await session.execute(
        select(RecipeRow).where(RecipeRow.id == recipe_id)
    )).scalar_one_or_none()

    if not recipe:
        raise HTTPException(404, "Recipe not found")

    short_id = _short_id(recipe_id)
    # In production, replace with actual domain
    base_url = "https://fitbites.io"

    description = recipe.description or ""
    if len(description) > 160:
        description = description[:157] + "..."

    # Build nutrition snippet for share text
    nutrition_parts = []
    if recipe.calories:
        nutrition_parts.append(f"{recipe.calories} cal")
    if recipe.protein_g:
        nutrition_parts.append(f"{recipe.protein_g}g protein")
    nutrition_text = " · ".join(nutrition_parts)

    share_description = f"{description}"
    if nutrition_text:
        share_description = f"{nutrition_text} — {description}" if description else nutrition_text

    return ShareLinkResponse(
        share_url=f"{base_url}/r/{short_id}",
        recipe_id=recipe_id,
        title=recipe.title,
        description=share_description,
        og_image_url=recipe.image_url if hasattr(recipe, "image_url") and recipe.image_url else None,
    )


# ── Open Graph page for link previews ──────────────────────────────────

@router.get("/r/{short_id}", response_class=HTMLResponse, include_in_schema=False)
async def share_page(
    short_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Serve an Open Graph HTML page for rich link previews on social media.
    
    When shared on iMessage, WhatsApp, Twitter, etc., this page provides:
    - Rich preview with recipe title, description, and image
    - Auto-redirect to the app (via universal links) or web fallback
    """
    # Find recipe by short ID
    result = await session.execute(select(RecipeRow))
    recipes = result.scalars().all()
    recipe = None
    for r in recipes:
        if _short_id(r.id) == short_id:
            recipe = r
            break

    if not recipe:
        return HTMLResponse(
            content="<html><body><h1>Recipe not found</h1><p>This recipe may have been removed.</p></body></html>",
            status_code=404,
        )

    image_url = getattr(recipe, "image_url", None) or "https://fitbites.io/og-default.png"
    description = recipe.description or "Discover healthy recipes on FitBites"
    if len(description) > 200:
        description = description[:197] + "..."

    nutrition = ""
    if recipe.calories:
        nutrition += f"{recipe.calories} cal"
    if recipe.protein_g:
        nutrition += f" · {recipe.protein_g}g protein"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{recipe.title} — FitBites</title>
    
    <!-- Open Graph -->
    <meta property="og:type" content="article">
    <meta property="og:title" content="{recipe.title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="{image_url}">
    <meta property="og:url" content="https://fitbites.io/r/{short_id}">
    <meta property="og:site_name" content="FitBites">
    
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{recipe.title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="{image_url}">
    
    <!-- iOS Universal Link / App Deep Link -->
    <meta name="apple-itunes-app" content="app-id=XXXXXXXXX, app-argument=fitbites://recipe/{recipe.id}">
    
    <!-- Auto-redirect to app or web -->
    <script>
        // Try to open the app first
        const appUrl = 'fitbites://recipe/{recipe.id}';
        const webUrl = 'https://fitbites.io/app/recipe/{recipe.id}';
        
        setTimeout(() => window.location = webUrl, 1500);
        window.location = appUrl;
    </script>
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', system-ui, sans-serif; 
               background: #0a0a0a; color: #fff; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }}
        .card {{ max-width: 480px; margin: 20px; text-align: center; }}
        .card img {{ width: 100%; border-radius: 16px; margin-bottom: 20px; }}
        h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .nutrition {{ color: #22c55e; font-size: 14px; font-weight: 600; margin-bottom: 12px; }}
        .desc {{ color: #a1a1aa; font-size: 16px; line-height: 1.5; margin-bottom: 24px; }}
        .cta {{ display: inline-block; padding: 14px 32px; background: #22c55e; color: #000;
                border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 16px; }}
        .cta:hover {{ background: #16a34a; }}
        .loading {{ color: #71717a; font-size: 13px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="{image_url}" alt="{recipe.title}" onerror="this.style.display='none'">
        <h1>{recipe.title}</h1>
        <div class="nutrition">{nutrition}</div>
        <p class="desc">{description}</p>
        <a class="cta" href="https://fitbites.io/app/recipe/{recipe.id}">View Recipe</a>
        <p class="loading">Opening FitBites...</p>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
