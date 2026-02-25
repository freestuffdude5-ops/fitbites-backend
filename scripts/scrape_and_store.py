"""Full pipeline: scrape Reddit → extract recipes → store in SQLite DB.

Works without any API keys. Uses public Reddit JSON + local extraction.
Run: python3 scripts/scrape_and_store.py
"""
import asyncio
import sys
import uuid
sys.path.insert(0, ".")

from src.scrapers.reddit_public import RedditPublicScraper
from src.services.recipe_extractor_local import extract_recipe_local
from src.services.viral_score import compute_viral_score
from src.services.affiliate import enrich_recipe


async def main():
    scraper = RedditPublicScraper()
    recipes = []

    print("🔍 Scraping Reddit for recipes...\n")

    subreddits = [
        "fitmeals", "EatCheapAndHealthy", "Volumeeating",
        "1200isplenty", "MealPrepSunday", "ketorecipes",
    ]

    async for raw_post in scraper.discover_recipes(hashtags=subreddits, limit=30):
        data = await scraper.extract_recipe_data(raw_post)
        recipe = extract_recipe_local(data)

        if recipe:
            recipe.id = str(uuid.uuid4())
            recipe.virality_score = compute_viral_score(recipe)

            # Add affiliate links to ingredients
            if recipe.ingredients:
                for ing in recipe.ingredients:
                    name = ing.name if hasattr(ing, 'name') else ing.get('name', '')
                    if name:
                        ing.affiliate_url = f"https://www.amazon.com/s?k={name.replace(' ', '+')}&tag=83apps01-20"

            recipes.append(recipe)
            cal = recipe.nutrition.calories if recipe.nutrition else "?"
            pro = f"{recipe.nutrition.protein_g}g" if recipe.nutrition else "?"
            ing = len(recipe.ingredients)
            print(f"  ✅ {recipe.title[:60]}")
            print(f"     📊 {cal} cal | 💪 {pro} protein | 🥗 {ing} ingredients | ⚡ virality: {recipe.virality_score}")

    await scraper.close()
    print(f"\n📊 Extracted {len(recipes)} recipes total")

    # Store in database
    if recipes:
        print("\n💾 Storing in database...")
        from src.db.engine import engine, async_session
        from src.db.tables import Base, RecipeRow
        from src.db.repository import RecipeRepository
        import src.analytics.tables  # noqa
        import src.db.user_tables  # noqa
        import src.db.meal_plan_tables  # noqa

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as session:
            repo = RecipeRepository(session)
            stored = 0
            for recipe in recipes:
                try:
                    await repo.upsert(recipe)
                    stored += 1
                except Exception as e:
                    print(f"  ⚠️  Failed to store: {recipe.title[:40]} — {e}")
            await session.commit()

        print(f"  ✅ Stored {stored} recipes in fitbites.db")

        # Show total count
        async with async_session() as session:
            repo = RecipeRepository(session)
            total = await repo.count()
            print(f"  📦 Total recipes in DB: {total}")

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
