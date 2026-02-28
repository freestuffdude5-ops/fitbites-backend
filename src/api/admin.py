"""Admin API endpoints for FitBites - protected by admin-only auth."""
from fastapi import APIRouter, Body, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.repository import RecipeRepository
from config.settings import settings

router = APIRouter(prefix="/api/v1/db-admin", tags=["db-admin"])


def verify_admin_key(x_admin_key: str = Header(None)) -> None:
    """Verify admin API key from request header (timing-safe)."""
    import hmac
    expected_key = settings.ADMIN_API_KEY
    if not expected_key:
        raise HTTPException(503, "Admin endpoints disabled (ADMIN_API_KEY not set)")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected_key):
        raise HTTPException(403, "Invalid admin key")


@router.post("/seed-database")
async def seed_database(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """
    Seed the database with initial recipes for development/production.
    
    Requires: X-Admin-Key header with valid admin API key.
    
    Returns count of recipes seeded.
    """
    from src.db.tables import RecipeRow
    from sqlalchemy import select, func
    
    # Check if database already has recipes
    result = await session.execute(select(func.count(RecipeRow.id)))
    existing_count = result.scalar()
    
    if existing_count > 0:
        return {
            "status": "skipped",
            "message": f"Database already has {existing_count} recipes. Clear first if you want to reseed.",
            "existing_recipes": existing_count,
        }
    
    # Import seed data
    import sys
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed", "seed.py")
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    
    # Run seeding
    await seed_module.seed()
    
    # Count new recipes
    result = await session.execute(select(func.count(RecipeRow.id)))
    new_count = result.scalar()
    
    return {
        "status": "success",
        "message": f"Database seeded with {new_count} recipes",
        "recipes_added": new_count,
    }


@router.post("/seed-extra")
async def seed_extra_recipes(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """Seed additional recipes (can run multiple times safely - dedupes by title)."""
    from src.db.tables import RecipeRow
    from sqlalchemy import select, func
    
    # Count before
    result = await session.execute(select(func.count(RecipeRow.id)))
    before = result.scalar()
    
    # Get existing titles
    existing = await session.execute(select(RecipeRow.title))
    existing_titles = {row[0] for row in existing.fetchall()}
    
    # Import extra seed data
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_extra", "seed_extra.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    
    import uuid, random
    from datetime import datetime, timedelta, timezone
    
    added = 0
    for r in mod.EXTRA_RECIPES:
        if r["title"] in existing_titles:
            continue
        now = datetime.now(timezone.utc)
        row = RecipeRow(
            id=str(uuid.uuid4()),
            title=r["title"],
            description=r.get("description"),
            creator_username=r["creator_username"],
            creator_display_name=r.get("creator_display_name"),
            creator_platform=r["creator_platform"],
            creator_profile_url=r.get("creator_profile_url"),
            creator_avatar_url=r.get("creator_avatar_url"),
            creator_follower_count=r.get("creator_follower_count"),
            platform=r["platform"],
            source_url=r["source_url"],
            thumbnail_url=r.get("thumbnail_url"),
            video_url=r.get("video_url"),
            ingredients=r["ingredients"],
            steps=r["steps"],
            tags=r.get("tags", []),
            calories=r.get("calories"),
            protein_g=r.get("protein_g"),
            carbs_g=r.get("carbs_g"),
            fat_g=r.get("fat_g"),
            fiber_g=r.get("fiber_g"),
            sugar_g=r.get("sugar_g"),
            servings=r.get("servings"),
            cook_time_minutes=r.get("cook_time_minutes"),
            difficulty=r.get("difficulty"),
            views=r.get("views"),
            likes=r.get("likes"),
            comments=r.get("comments"),
            shares=r.get("shares"),
            virality_score=random.randint(60, 95),
            scraped_at=now - timedelta(hours=random.randint(1, 72)),
            published_at=now - timedelta(days=random.randint(1, 90)),
        )
        session.add(row)
        added += 1
    
    await session.commit()
    
    result = await session.execute(select(func.count(RecipeRow.id)))
    after = result.scalar()
    
    return {"status": "success", "added": added, "total": after, "skipped_duplicates": len(mod.EXTRA_RECIPES) - added}


@router.post("/delete-recipes-by-ids")
async def delete_recipes_by_ids(
    recipe_ids: list[str] = Body(..., embed=True),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """
    Delete specific recipes by their UUIDs.
    
    Requires: X-Admin-Key header with valid admin API key.
    Body: {"recipe_ids": ["uuid1", "uuid2", ...]}
    """
    from src.db.tables import RecipeRow
    from sqlalchemy import select, delete, func
    
    if not recipe_ids:
        raise HTTPException(400, "No recipe IDs provided")
    
    # Get titles before deletion
    result = await session.execute(
        select(RecipeRow.id, RecipeRow.title).where(RecipeRow.id.in_(recipe_ids))
    )
    recipes_to_delete = result.fetchall()
    
    # Delete recipes
    result = await session.execute(
        delete(RecipeRow).where(RecipeRow.id.in_(recipe_ids))
    )
    deleted_count = result.rowcount
    await session.commit()
    
    return {
        "status": "success",
        "deleted": deleted_count,
        "expected": len(recipe_ids),
        "recipes": [{"id": str(r.id), "title": r.title} for r in recipes_to_delete]
    }


@router.delete("/clear-recipes")
async def clear_recipes(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """
    Clear all recipes from the database (DANGEROUS - use with caution).
    
    Requires: X-Admin-Key header with valid admin API key.
    """
    from src.db.tables import RecipeRow
    from sqlalchemy import select, delete, func
    
    # Count before deletion
    result = await session.execute(select(func.count(RecipeRow.id)))
    count_before = result.scalar()
    
    if count_before == 0:
        return {"status": "empty", "message": "Database already empty", "deleted": 0}
    
    # Delete all recipes
    await session.execute(delete(RecipeRow))
    await session.commit()
    
    return {
        "status": "success",
        "message": f"Deleted {count_before} recipes",
        "deleted": count_before,
    }


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """Get database statistics (recipe count, user count, etc.)."""
    from src.db.tables import RecipeRow
    from src.db.user_tables import UserRow
    from sqlalchemy import select, func
    
    recipe_count = (await session.execute(select(func.count(RecipeRow.id)))).scalar()
    user_count = (await session.execute(select(func.count(UserRow.id)))).scalar()
    
    return {
        "recipes": recipe_count,
        "users": user_count,
        "database_url": settings.DATABASE_URL.split("@")[-1] if settings.DATABASE_URL else "not set",  # Hide password
    }


@router.post("/import-bulk")
async def import_bulk_recipes(
    request_data: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_admin_key),
):
    """Import recipes in bulk from JSON payload. Admin-only.
    
    Expects: {"recipes": [{title, description, source_platform, source_url, ...}]}
    """
    from src.db.tables import RecipeRow
    from sqlalchemy import select, func
    import uuid, random
    from datetime import datetime, timedelta, timezone
    
    recipes_data = request_data.get("recipes", [])
    if not recipes_data:
        raise HTTPException(400, "No recipes provided")
    
    inserted = 0
    skipped = 0
    errors = []
    
    # Get existing source_urls for dedup
    existing_result = await session.execute(select(RecipeRow.source_url))
    existing_urls = {row[0] for row in existing_result.fetchall()}
    
    for rd in recipes_data:
        try:
            source_url = rd.get("source_url", "")
            if not source_url:
                errors.append(f"Missing source_url for: {rd.get('title','?')[:40]}")
                continue
            if source_url in existing_urls:
                skipped += 1
                continue
            
            now = datetime.now(timezone.utc)
            platform = rd.get("source_platform", rd.get("platform", "reddit"))
            author = rd.get("source_author", rd.get("creator_username", "unknown"))
            
            row = RecipeRow(
                id=str(uuid.uuid4()),
                title=rd.get("title", "Untitled")[:500],
                description=rd.get("description", ""),
                creator_username=author,
                creator_display_name=author,
                creator_platform=platform,
                creator_profile_url=rd.get("creator_profile_url", f"https://{platform}.com/@{author}"),
                creator_avatar_url=rd.get("creator_avatar_url"),
                creator_follower_count=rd.get("creator_follower_count"),
                platform=platform,
                source_url=source_url,
                thumbnail_url=rd.get("thumbnail_url", ""),
                video_url=rd.get("video_url"),
                ingredients=rd.get("ingredients", []),
                steps=rd.get("steps", []),
                tags=rd.get("tags", []),
                calories=rd.get("calories"),
                protein_g=rd.get("protein_g"),
                carbs_g=rd.get("carbs_g"),
                fat_g=rd.get("fat_g"),
                fiber_g=rd.get("fiber_g"),
                sugar_g=rd.get("sugar_g"),
                servings=rd.get("servings", 1),
                views=int(rd.get("engagement_score", rd.get("views", 0))),
                likes=rd.get("likes"),
                comments=rd.get("comments"),
                shares=rd.get("shares"),
                cook_time_minutes=rd.get("cook_time_min", rd.get("cook_time_minutes")),
                difficulty=rd.get("difficulty"),
                virality_score=float(rd.get("quality_score", rd.get("virality_score", random.randint(40, 80)))),
                scraped_at=now,
                published_at=now - timedelta(days=random.randint(1, 30)),
            )
            session.add(row)
            existing_urls.add(source_url)
            inserted += 1
        except Exception as e:
            errors.append(f"Error with '{rd.get('title','?')[:40]}': {str(e)}")
    
    await session.commit()
    
    total = (await session.execute(select(func.count(RecipeRow.id)))).scalar()
    return {
        "status": "success",
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors[:10],
        "total_recipes": total,
    }
