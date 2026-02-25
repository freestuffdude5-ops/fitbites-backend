"""Collections API — premium recipe organization.

Users can create named collections to organize saved recipes:
- "Weeknight Dinners 🍝"
- "High Protein Meal Prep 💪"
- "Date Night Recipes ❤️"

Features:
- CRUD collections with emoji icons and descriptions
- Add/remove recipes from collections
- Reorder collections and items within them
- Public collections (shareable link)
- Cover image from first recipe or manual pick
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.collection_tables import CollectionRow, CollectionItemRow
from src.db.tables import RecipeRow
from src.auth import require_user
from src.db.user_tables import UserRow

router = APIRouter(prefix="/api/v1", tags=["collections"])


# ── Schemas ──────────────────────────────────────────────────────────────

class CreateCollectionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    emoji: str | None = Field(None, max_length=10)
    is_public: bool = False

class UpdateCollectionRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    emoji: str | None = Field(None, max_length=10)
    is_public: bool | None = None
    cover_recipe_id: str | None = None

class AddToCollectionRequest(BaseModel):
    recipe_id: str
    notes: str | None = Field(None, max_length=500)

class ReorderRequest(BaseModel):
    ordered_ids: list[str] = Field(..., min_length=1, max_length=200)

class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str | None
    emoji: str | None
    is_public: bool
    recipe_count: int
    cover_image_url: str | None = None
    created_at: str
    updated_at: str

class CollectionDetailResponse(CollectionResponse):
    recipes: list[dict]

class CollectionItemResponse(BaseModel):
    id: str
    recipe_id: str
    title: str
    calories: int | None
    protein_g: float | None
    image_url: str | None = None
    notes: str | None
    added_at: str


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_collection_owned(
    collection_id: str, user: UserRow, session: AsyncSession
) -> CollectionRow:
    result = await session.execute(
        select(CollectionRow).where(
            CollectionRow.id == collection_id,
            CollectionRow.user_id == user.id,
        )
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


async def _get_cover_url(collection: CollectionRow, session: AsyncSession) -> str | None:
    """Get cover image URL — from cover_recipe_id or first recipe."""
    target_id = collection.cover_recipe_id
    if not target_id:
        # Use first item's recipe
        result = await session.execute(
            select(CollectionItemRow.recipe_id)
            .where(CollectionItemRow.collection_id == collection.id)
            .order_by(CollectionItemRow.position)
            .limit(1)
        )
        target_id = result.scalar_one_or_none()
    if not target_id:
        return None
    result = await session.execute(
        select(RecipeRow.thumbnail_url).where(RecipeRow.id == target_id)
    )
    return result.scalar_one_or_none()


def _format_collection(c: CollectionRow, cover_url: str | None = None) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "emoji": c.emoji,
        "is_public": c.is_public,
        "recipe_count": c.recipe_count,
        "cover_image_url": cover_url,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ── Routes ───────────────────────────────────────────────────────────────

@router.post("/collections", status_code=201)
async def create_collection(
    body: CreateCollectionRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new recipe collection."""
    # Check for duplicate name
    existing = await session.execute(
        select(CollectionRow).where(
            CollectionRow.user_id == user.id,
            CollectionRow.name == body.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Collection with this name already exists")

    # Get max position for ordering
    result = await session.execute(
        select(func.coalesce(func.max(CollectionRow.position), -1))
        .where(CollectionRow.user_id == user.id)
    )
    max_pos = result.scalar() or 0

    collection = CollectionRow(
        user_id=user.id,
        name=body.name,
        description=body.description,
        emoji=body.emoji,
        is_public=body.is_public,
        position=max_pos + 1,
    )
    session.add(collection)
    await session.commit()
    await session.refresh(collection)

    return _format_collection(collection)


@router.get("/collections")
async def list_collections(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List all collections for the authenticated user."""
    result = await session.execute(
        select(CollectionRow)
        .where(CollectionRow.user_id == user.id)
        .order_by(CollectionRow.position)
    )
    collections = result.scalars().all()

    items = []
    for c in collections:
        cover_url = await _get_cover_url(c, session)
        items.append(_format_collection(c, cover_url))

    return {"collections": items, "total": len(items)}


@router.get("/collections/{collection_id}")
async def get_collection(
    collection_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get collection details with recipes."""
    collection = await _get_collection_owned(collection_id, user, session)
    cover_url = await _get_cover_url(collection, session)

    # Get recipes in collection
    result = await session.execute(
        select(CollectionItemRow, RecipeRow)
        .join(RecipeRow, CollectionItemRow.recipe_id == RecipeRow.id)
        .where(CollectionItemRow.collection_id == collection_id)
        .order_by(CollectionItemRow.position)
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    recipes = []
    for item, recipe in rows:
        recipes.append({
            "item_id": item.id,
            "recipe_id": recipe.id,
            "title": recipe.title,
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
            "carbs_g": recipe.carbs_g,
            "fat_g": recipe.fat_g,
            "cook_time_minutes": recipe.cook_time_minutes,
            "thumbnail_url": getattr(recipe, "thumbnail_url", None),
            "creator_username": recipe.creator_username,
            "virality_score": recipe.virality_score,
            "notes": item.notes,
            "added_at": item.added_at.isoformat() if item.added_at else None,
        })

    data = _format_collection(collection, cover_url)
    data["recipes"] = recipes
    return data


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: str,
    body: UpdateCollectionRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update collection metadata."""
    collection = await _get_collection_owned(collection_id, user, session)

    if body.name is not None and body.name != collection.name:
        # Check duplicate name
        existing = await session.execute(
            select(CollectionRow).where(
                CollectionRow.user_id == user.id,
                CollectionRow.name == body.name,
                CollectionRow.id != collection_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Collection with this name already exists")
        collection.name = body.name

    if body.description is not None:
        collection.description = body.description
    if body.emoji is not None:
        collection.emoji = body.emoji
    if body.is_public is not None:
        collection.is_public = body.is_public
    if body.cover_recipe_id is not None:
        collection.cover_recipe_id = body.cover_recipe_id

    collection.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(collection)

    cover_url = await _get_cover_url(collection, session)
    return _format_collection(collection, cover_url)


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a collection (recipes are NOT deleted, just unlinked)."""
    collection = await _get_collection_owned(collection_id, user, session)
    await session.delete(collection)
    await session.commit()


@router.post("/collections/{collection_id}/recipes", status_code=201)
async def add_recipe_to_collection(
    collection_id: str,
    body: AddToCollectionRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Add a recipe to a collection."""
    collection = await _get_collection_owned(collection_id, user, session)

    # Verify recipe exists
    recipe = await session.execute(
        select(RecipeRow).where(RecipeRow.id == body.recipe_id)
    )
    if not recipe.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Check if already in collection
    existing = await session.execute(
        select(CollectionItemRow).where(
            CollectionItemRow.collection_id == collection_id,
            CollectionItemRow.recipe_id == body.recipe_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Recipe already in this collection")

    # Get max position
    result = await session.execute(
        select(func.coalesce(func.max(CollectionItemRow.position), -1))
        .where(CollectionItemRow.collection_id == collection_id)
    )
    max_pos = result.scalar() or 0

    item = CollectionItemRow(
        collection_id=collection_id,
        recipe_id=body.recipe_id,
        added_by=user.id,
        notes=body.notes,
        position=max_pos + 1,
    )
    session.add(item)

    # Update count
    collection.recipe_count = (collection.recipe_count or 0) + 1
    collection.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(item)

    return {
        "id": item.id,
        "collection_id": collection_id,
        "recipe_id": body.recipe_id,
        "notes": item.notes,
        "position": item.position,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


@router.delete("/collections/{collection_id}/recipes/{recipe_id}", status_code=204)
async def remove_recipe_from_collection(
    collection_id: str,
    recipe_id: str,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove a recipe from a collection."""
    collection = await _get_collection_owned(collection_id, user, session)

    result = await session.execute(
        select(CollectionItemRow).where(
            CollectionItemRow.collection_id == collection_id,
            CollectionItemRow.recipe_id == recipe_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Recipe not in this collection")

    await session.delete(item)
    collection.recipe_count = max(0, (collection.recipe_count or 1) - 1)
    collection.updated_at = datetime.now(timezone.utc)
    await session.commit()


@router.post("/collections/{collection_id}/reorder")
async def reorder_collection_items(
    collection_id: str,
    body: ReorderRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Reorder recipes within a collection. Send ordered list of item IDs."""
    await _get_collection_owned(collection_id, user, session)

    for i, item_id in enumerate(body.ordered_ids):
        await session.execute(
            update(CollectionItemRow)
            .where(
                CollectionItemRow.id == item_id,
                CollectionItemRow.collection_id == collection_id,
            )
            .values(position=i)
        )
    await session.commit()
    return {"status": "reordered", "count": len(body.ordered_ids)}


@router.post("/collections/reorder")
async def reorder_collections(
    body: ReorderRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Reorder collections. Send ordered list of collection IDs."""
    for i, coll_id in enumerate(body.ordered_ids):
        await session.execute(
            update(CollectionRow)
            .where(
                CollectionRow.id == coll_id,
                CollectionRow.user_id == user.id,
            )
            .values(position=i)
        )
    await session.commit()
    return {"status": "reordered", "count": len(body.ordered_ids)}


@router.get("/collections/{collection_id}/public")
async def get_public_collection(
    collection_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """View a public collection (no auth required)."""
    result = await session.execute(
        select(CollectionRow).where(
            CollectionRow.id == collection_id,
            CollectionRow.is_public == True,
        )
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found or is private")

    cover_url = await _get_cover_url(collection, session)

    # Get recipes
    result = await session.execute(
        select(CollectionItemRow, RecipeRow)
        .join(RecipeRow, CollectionItemRow.recipe_id == RecipeRow.id)
        .where(CollectionItemRow.collection_id == collection_id)
        .order_by(CollectionItemRow.position)
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    recipes = []
    for item, recipe in rows:
        recipes.append({
            "recipe_id": recipe.id,
            "title": recipe.title,
            "calories": recipe.calories,
            "protein_g": recipe.protein_g,
            "thumbnail_url": getattr(recipe, "thumbnail_url", None),
            "creator_username": recipe.creator_username,
        })

    # Get owner info
    from src.db.user_tables import UserRow as URow
    owner = await session.execute(
        select(URow.display_name, URow.avatar_url).where(URow.id == collection.user_id)
    )
    owner_row = owner.one_or_none()

    data = _format_collection(collection, cover_url)
    data["recipes"] = recipes
    data["owner"] = {
        "display_name": owner_row[0] if owner_row else None,
        "avatar_url": owner_row[1] if owner_row else None,
    } if owner_row else None
    return data
