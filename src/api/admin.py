"""Admin API endpoints for FitBites - protected by admin-only auth."""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.repository import RecipeRepository
from config.settings import settings

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def verify_admin_key(x_admin_key: str = Header(None)) -> None:
    """Verify admin API key from request header."""
    expected_key = settings.ADMIN_API_KEY
    if not expected_key:
        raise HTTPException(503, "Admin endpoints disabled (ADMIN_API_KEY not set)")
    if x_admin_key != expected_key:
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
    await seed_module.seed_database()
    
    # Count new recipes
    result = await session.execute(select(func.count(RecipeRow.id)))
    new_count = result.scalar()
    
    return {
        "status": "success",
        "message": f"Database seeded with {new_count} recipes",
        "recipes_added": new_count,
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
