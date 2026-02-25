"""User API routes — registration, saved recipes, grocery lists.

This is the core engagement + monetization path:
  Register → Browse → Save Recipe → Build Grocery List → Shop All (affiliate $$$)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow, SavedRecipeRow, GroceryListRow
from src.db.tables import RecipeRow
from src.services.affiliate import enrich_ingredient, get_shop_all_url, parse_ingredient

router = APIRouter(prefix="/api/v1", tags=["users"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    device_id: str | None = Field(None, max_length=64, description="For anonymous sign-up")
    email: str | None = Field(None, max_length=320, description="For email-based auth")
    display_name: str | None = Field(None, max_length=100)

class UserResponse(BaseModel):
    id: str
    device_id: str | None
    email: str | None
    display_name: str | None
    preferences: dict

class SaveRecipeRequest(BaseModel):
    recipe_id: str
    collection: str | None = None
    notes: str | None = None

class UpdateSaveRequest(BaseModel):
    collection: str | None = None
    notes: str | None = None

class GroceryListCreateRequest(BaseModel):
    name: str = "My Grocery List"
    recipe_ids: list[str] = Field(..., min_length=1, max_length=50,
                                   description="Recipe IDs to generate grocery list from")

class GroceryItemUpdate(BaseModel):
    index: int
    checked: bool

class PreferencesUpdate(BaseModel):
    dietary: list[str] | None = None  # e.g. ["keto", "gluten-free"]
    max_calories: int | None = None
    min_protein: float | None = None
    excluded_ingredients: list[str] | None = None


# ── User Registration ────────────────────────────────────────────────────────

@router.post("/users/register", status_code=201)
async def register_user(req: RegisterRequest, session: AsyncSession = Depends(get_session)):
    """Register a new user (anonymous via device_id, or via email).

    Returns existing user if device_id/email already registered.
    """
    if not req.device_id and not req.email:
        raise HTTPException(400, "Provide either device_id or email")

    # Check for existing user
    if req.device_id:
        existing = (await session.execute(
            select(UserRow).where(UserRow.device_id == req.device_id)
        )).scalar_one_or_none()
    elif req.email:
        existing = (await session.execute(
            select(UserRow).where(UserRow.email == req.email)
        )).scalar_one_or_none()
    else:
        existing = None

    if existing:
        existing.last_active_at = datetime.now(timezone.utc)
        await session.commit()
        return _user_response(existing)

    user = UserRow(
        id=str(uuid.uuid4()),
        device_id=req.device_id,
        email=req.email,
        display_name=req.display_name,
        preferences={},
    )
    session.add(user)
    await session.commit()
    return _user_response(user)


@router.get("/users/{user_id}")
async def get_user(user_id: str, session: AsyncSession = Depends(get_session)):
    """Get user profile."""
    user = await _get_user_or_404(user_id, session)
    return _user_response(user)


@router.patch("/users/{user_id}/preferences")
async def update_preferences(
    user_id: str,
    prefs: PreferencesUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update user dietary preferences (used for personalized recommendations)."""
    user = await _get_user_or_404(user_id, session)
    current = user.preferences or {}
    updates = prefs.model_dump(exclude_none=True)
    current.update(updates)
    user.preferences = current
    await session.commit()
    return {"preferences": current}


# ── Saved Recipes (Favorites) ───────────────────────────────────────────────

@router.post("/users/{user_id}/saved", status_code=201)
async def save_recipe(
    user_id: str,
    req: SaveRecipeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Save a recipe to the user's collection. Idempotent — re-saving updates collection/notes."""
    await _get_user_or_404(user_id, session)

    # Verify recipe exists
    recipe = (await session.execute(
        select(RecipeRow).where(RecipeRow.id == req.recipe_id)
    )).scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    # Check if already saved
    existing = (await session.execute(
        select(SavedRecipeRow).where(
            SavedRecipeRow.user_id == user_id,
            SavedRecipeRow.recipe_id == req.recipe_id,
        )
    )).scalar_one_or_none()

    if existing:
        existing.collection = req.collection or existing.collection
        existing.notes = req.notes or existing.notes
        await session.commit()
        return {"status": "updated", "saved_id": existing.id}

    saved = SavedRecipeRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        recipe_id=req.recipe_id,
        collection=req.collection,
        notes=req.notes,
    )
    session.add(saved)
    await session.commit()
    return {"status": "saved", "saved_id": saved.id}


@router.get("/users/{user_id}/saved")
async def list_saved_recipes(
    user_id: str,
    collection: str | None = Query(None, description="Filter by collection name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List user's saved recipes with full recipe data + collection info."""
    await _get_user_or_404(user_id, session)

    stmt = (
        select(SavedRecipeRow, RecipeRow)
        .join(RecipeRow, SavedRecipeRow.recipe_id == RecipeRow.id)
        .where(SavedRecipeRow.user_id == user_id)
    )
    if collection:
        stmt = stmt.where(SavedRecipeRow.collection == collection)
    stmt = stmt.order_by(SavedRecipeRow.saved_at.desc()).offset(offset).limit(limit)

    results = (await session.execute(stmt)).all()

    # Count total
    count_stmt = select(func.count(SavedRecipeRow.id)).where(SavedRecipeRow.user_id == user_id)
    if collection:
        count_stmt = count_stmt.where(SavedRecipeRow.collection == collection)
    total = (await session.execute(count_stmt)).scalar() or 0

    data = []
    for saved, recipe in results:
        data.append({
            "saved_id": saved.id,
            "collection": saved.collection,
            "notes": saved.notes,
            "saved_at": saved.saved_at.isoformat() if saved.saved_at else None,
            "recipe": {
                "id": recipe.id,
                "title": recipe.title,
                "thumbnail_url": recipe.thumbnail_url,
                "calories": recipe.calories,
                "protein_g": recipe.protein_g,
                "cook_time_minutes": recipe.cook_time_minutes,
                "virality_score": recipe.virality_score,
                "platform": recipe.platform.value if recipe.platform else None,
            },
        })

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total},
    }


@router.get("/users/{user_id}/collections")
async def list_collections(user_id: str, session: AsyncSession = Depends(get_session)):
    """List all collections with recipe counts."""
    await _get_user_or_404(user_id, session)
    stmt = (
        select(SavedRecipeRow.collection, func.count().label("count"))
        .where(SavedRecipeRow.user_id == user_id)
        .group_by(SavedRecipeRow.collection)
    )
    results = (await session.execute(stmt)).all()
    return {
        "collections": [
            {"name": name or "Unsorted", "count": count}
            for name, count in results
        ]
    }


@router.delete("/users/{user_id}/saved/{recipe_id}", status_code=204)
async def unsave_recipe(
    user_id: str,
    recipe_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a recipe from saved."""
    result = await session.execute(
        delete(SavedRecipeRow).where(
            SavedRecipeRow.user_id == user_id,
            SavedRecipeRow.recipe_id == recipe_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Saved recipe not found")
    await session.commit()


# ── Grocery Lists ────────────────────────────────────────────────────────────

@router.post("/users/{user_id}/grocery-lists", status_code=201)
async def create_grocery_list(
    user_id: str,
    req: GroceryListCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Generate a grocery list from one or more recipes.

    Aggregates ingredients, deduplicates similar items, and attaches
    affiliate links for each ingredient. This is the primary monetization path.
    """
    await _get_user_or_404(user_id, session)

    # Fetch all requested recipes
    recipes = (await session.execute(
        select(RecipeRow).where(RecipeRow.id.in_(req.recipe_ids))
    )).scalars().all()

    if not recipes:
        raise HTTPException(404, "No valid recipes found")

    # Aggregate ingredients across recipes
    items = []
    seen_normalized = {}  # normalized_name → index (for dedup)

    for recipe in recipes:
        for ing_dict in (recipe.ingredients or []):
            raw = ing_dict.get("name", "") or ""
            amount = ing_dict.get("quantity", "") or ""
            if not raw:
                continue

            _, normalized = parse_ingredient(raw)
            enriched = enrich_ingredient(raw)

            if normalized in seen_normalized:
                # Combine amounts for duplicate ingredients
                idx = seen_normalized[normalized]
                existing_amount = items[idx]["amount"]
                if amount and existing_amount:
                    items[idx]["amount"] = f"{existing_amount} + {amount}"
                items[idx]["recipe_ids"].append(recipe.id)
            else:
                seen_normalized[normalized] = len(items)
                items.append({
                    "ingredient": raw,
                    "normalized": normalized,
                    "amount": amount,
                    "checked": False,
                    "recipe_ids": [recipe.id],
                    "affiliate": enriched.to_dict() if enriched else None,
                })

    # Generate shop-all link
    all_ingredients = [item["ingredient"] for item in items]
    shop_all = get_shop_all_url(all_ingredients) if all_ingredients else None

    grocery_list = GroceryListRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=req.name,
        items=items,
    )
    session.add(grocery_list)
    await session.commit()

    return {
        "id": grocery_list.id,
        "name": grocery_list.name,
        "item_count": len(items),
        "items": items,
        "shop_all": shop_all,
        "recipe_count": len(recipes),
    }


@router.get("/users/{user_id}/grocery-lists")
async def list_grocery_lists(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List user's grocery lists (most recent first)."""
    await _get_user_or_404(user_id, session)
    stmt = (
        select(GroceryListRow)
        .where(GroceryListRow.user_id == user_id)
        .order_by(GroceryListRow.created_at.desc())
        .limit(limit)
    )
    results = (await session.execute(stmt)).scalars().all()
    return {
        "data": [
            {
                "id": gl.id,
                "name": gl.name,
                "item_count": len(gl.items or []),
                "created_at": gl.created_at.isoformat() if gl.created_at else None,
            }
            for gl in results
        ]
    }


@router.get("/users/{user_id}/grocery-lists/{list_id}")
async def get_grocery_list(
    user_id: str,
    list_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a grocery list with all items and affiliate links."""
    gl = (await session.execute(
        select(GroceryListRow).where(
            GroceryListRow.id == list_id,
            GroceryListRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not gl:
        raise HTTPException(404, "Grocery list not found")

    items = gl.items or []
    all_ingredients = [item["ingredient"] for item in items]
    shop_all = get_shop_all_url(all_ingredients) if all_ingredients else None

    return {
        "id": gl.id,
        "name": gl.name,
        "items": items,
        "item_count": len(items),
        "shop_all": shop_all,
        "created_at": gl.created_at.isoformat() if gl.created_at else None,
    }


@router.patch("/users/{user_id}/grocery-lists/{list_id}/check")
async def check_grocery_item(
    user_id: str,
    list_id: str,
    update: GroceryItemUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Toggle checked state of a grocery list item."""
    gl = (await session.execute(
        select(GroceryListRow).where(
            GroceryListRow.id == list_id,
            GroceryListRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not gl:
        raise HTTPException(404, "Grocery list not found")

    items = list(gl.items or [])
    if update.index < 0 or update.index >= len(items):
        raise HTTPException(400, "Invalid item index")

    items[update.index]["checked"] = update.checked
    gl.items = items
    gl.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {"status": "updated", "item": items[update.index]}


@router.delete("/users/{user_id}/grocery-lists/{list_id}", status_code=204)
async def delete_grocery_list(
    user_id: str,
    list_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a grocery list."""
    result = await session.execute(
        delete(GroceryListRow).where(
            GroceryListRow.id == list_id,
            GroceryListRow.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Grocery list not found")
    await session.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_user_or_404(user_id: str, session: AsyncSession) -> UserRow:
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return user


def _user_response(user: UserRow) -> dict:
    return {
        "id": user.id,
        "device_id": user.device_id,
        "email": user.email,
        "display_name": user.display_name,
        "preferences": user.preferences or {},
    }
