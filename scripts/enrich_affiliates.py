"""Enrich all recipes in the DB with Amazon affiliate links on their ingredients."""
import asyncio
import sys
sys.path.insert(0, ".")

from urllib.parse import quote_plus
from src.db.engine import engine, async_session
from src.db.tables import RecipeRow

AMAZON_TAG = "83apps01-20"


def make_amazon_search_url(ingredient_name: str) -> str:
    """Generate Amazon search URL with affiliate tag for an ingredient."""
    q = quote_plus(ingredient_name)
    return f"https://www.amazon.com/s?k={q}&tag={AMAZON_TAG}"


async def main():
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(RecipeRow))
        rows = result.scalars().all()
        
        updated = 0
        for row in rows:
            if not row.ingredients:
                continue
            
            changed = False
            new_ingredients = []
            for ing in row.ingredients:
                if not ing.get("affiliate_url"):
                    ing["affiliate_url"] = make_amazon_search_url(ing["name"])
                    changed = True
                new_ingredients.append(ing)
            
            if changed:
                # Force SQLAlchemy to detect JSON mutation
                from sqlalchemy.orm.attributes import flag_modified
                row.ingredients = new_ingredients
                flag_modified(row, "ingredients")
                updated += 1
        
        await session.commit()
        print(f"✅ Enriched {updated} recipes with Amazon affiliate links (tag: {AMAZON_TAG})")


if __name__ == "__main__":
    asyncio.run(main())
