"""Delete low-quality recipes from production database.

This script runs via: railway run python delete_low_quality_recipes.py
"""
import asyncio
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

async def main():
    print("=" * 80)
    print("FitBites Production - Delete Low Quality Recipes")
    print("=" * 80)
    print()
    
    # Import database modules
    from src.db.engine import async_session
    from src.db.tables import RecipeRow
    from sqlalchemy import select, delete, func
    
    # IDs to delete (from audit)
    ids_to_delete = [
        "0a7500d4-ada0-47c8-bc61-4b0e5adea90c",  # Multi-recipe: Full Day of Eating
        "86ebf426-33a4-4261-80ac-634f3b75083b",  # Missing macros
        "2154ea4a-8c3d-4ae9-bae6-3853b39c96e8",
        "7f6cee6c-7964-4d5a-a269-e507718bbc3f",
        "ae5bb857-7ffe-4b49-9829-b1c61b24aa7c",
        "8b66c2e3-bd9a-4dc1-b816-2a77efd5f711",
        "d3745728-2e9e-4acd-b674-a7df5fb44b6d",
        "1a7d8783-a8b2-4096-ac9f-0d156e978382",
        "cf24e6b7-0d88-47c9-b357-ad5e9f82f904",
        "99a74d07-313e-4908-a171-11678b7f8490",
        "d7e86605-a75d-4925-aae0-5f9c91604792",
        "fb75ca82-e203-4ff0-bfc9-3b50c6cd625e",
        "fe0bfeb8-e8d8-4c5d-90b1-adb7d7450e33",
        "a2946dc3-44e6-4e8f-a838-8df00f8984c8",
        "315b4a5b-6ea1-4004-b68a-1ccfd6f6bdeb",
        "18a50a4a-37d1-426a-8887-62cc44c061c7",
        "7e9dfe50-6505-4956-af29-0239eae76354",
        "b86f5301-413f-4c3f-b016-0ef60c0e7eb7",
        "f3bf5ad4-be56-4c88-b57d-3a7009f458e1",
        "7ae7cd79-93bf-47d1-a21e-c65c6723a9f7",
        "15a05de8-bc23-4b04-896c-33b9eeda44f5",
    ]
    
    print(f"Recipes to delete: {len(ids_to_delete)}")
    print()
    
    async with async_session() as session:
        # Count before
        result = await session.execute(select(func.count(RecipeRow.id)))
        before_count = result.scalar()
        print(f"📊 Recipes before deletion: {before_count}")
        
        # Get titles of recipes being deleted (for logging)
        result = await session.execute(
            select(RecipeRow.id, RecipeRow.title).where(
                RecipeRow.id.in_(ids_to_delete)
            )
        )
        recipes_to_delete = result.fetchall()
        
        print(f"\n🗑️  Deleting {len(recipes_to_delete)} recipes:")
        for recipe_id, title in recipes_to_delete:
            print(f"  - {title[:70]}")
        print()
        
        # Delete recipes
        result = await session.execute(
            delete(RecipeRow).where(RecipeRow.id.in_(ids_to_delete))
        )
        deleted_count = result.rowcount
        await session.commit()
        
        # Count after
        result = await session.execute(select(func.count(RecipeRow.id)))
        after_count = result.scalar()
        
        print("=" * 80)
        print("DELETION COMPLETE")
        print("=" * 80)
        print(f"Recipes before:  {before_count}")
        print(f"Recipes deleted: {deleted_count}")
        print(f"Recipes after:   {after_count}")
        print("=" * 80)
        print()
        
        if deleted_count == len(ids_to_delete):
            print("✅ All low-quality recipes successfully deleted")
            print()
            print("Breakdown:")
            print("  - 1 multi-recipe compilation (Full Day of Eating)")
            print("  - 20 recipes with missing macros (incomplete data)")
            return 0
        else:
            print(f"⚠️  Warning: Expected to delete {len(ids_to_delete)}, actually deleted {deleted_count}")
            return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
