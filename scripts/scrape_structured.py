"""Scrape Reddit for STRUCTURED recipes — posts with actual ingredients & steps.

Targets subreddits known for structured recipe posts, filters aggressively
for posts containing ingredient lists, and uses the local extractor.
"""
import asyncio
import sys
import uuid
sys.path.insert(0, ".")

from src.scrapers.reddit_public import RedditPublicScraper
from src.services.recipe_extractor_local import extract_recipe_local
from src.services.viral_score import compute_viral_score


# Subreddits with the most structured recipe posts
STRUCTURED_SUBS = [
    "recipes",
    "ketorecipes",
    "veganrecipes",
    "GifRecipes",
    "Cooking",
    "fitmeals",
    "EatCheapAndHealthy",
    "1200isplenty",
    "MealPrepSunday",
    "Volumeeating",
]


def has_ingredients(text: str) -> bool:
    """Check if text has an actual ingredient list."""
    import re
    lines = text.split("\n")
    bullet_count = 0
    for line in lines:
        stripped = line.strip().replace("\\-", "-").replace("\\*", "*")
        if re.match(r'^[\-\*•]\s+\S', stripped):
            bullet_count += 1
    # At least 3 bullet points = likely ingredient list
    return bullet_count >= 3


async def main():
    scraper = RedditPublicScraper()
    good_recipes = []
    total_checked = 0

    print("🔍 Scraping Reddit for STRUCTURED recipes (with ingredients)...\n")

    async for raw_post in scraper.discover_recipes(hashtags=STRUCTURED_SUBS, limit=100):
        total_checked += 1
        data = await scraper.extract_recipe_data(raw_post)

        # Only keep posts with actual ingredient lists
        desc = data.get("description", "")
        if not has_ingredients(desc):
            continue

        recipe = extract_recipe_local(data)
        if recipe and len(recipe.ingredients) >= 3:
            recipe.id = str(uuid.uuid4())
            recipe.virality_score = compute_viral_score(recipe)

            # Add affiliate links
            for ing in recipe.ingredients:
                name = ing.name if hasattr(ing, 'name') else ""
                if name:
                    ing.affiliate_url = f"https://www.amazon.com/s?k={name.replace(' ', '+')}&tag=83apps01-20"

            good_recipes.append(recipe)
            cal = recipe.nutrition.calories if recipe.nutrition else "?"
            pro = f"{recipe.nutrition.protein_g}g" if recipe.nutrition else "?"
            print(f"  ✅ {recipe.title[:60]}")
            print(f"     📊 {cal} cal | 💪 {pro} protein | 🥗 {len(recipe.ingredients)} ingredients")
            print(f"     👍 {recipe.likes} | 💬 {recipe.comments} | r/{data.get('subreddit')}")
            print()

    await scraper.close()
    print(f"\n📊 Checked {total_checked} posts → Found {len(good_recipes)} structured recipes")

    if good_recipes:
        print("\n💾 Storing in database...")
        from src.db.engine import engine, async_session
        from src.db.tables import Base, RecipeRow
        from src.db.repository import RecipeRepository
        import src.analytics.tables
        import src.db.user_tables
        import src.db.meal_plan_tables

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as session:
            repo = RecipeRepository(session)
            stored = 0
            for recipe in good_recipes:
                try:
                    await repo.upsert(recipe)
                    stored += 1
                except Exception as e:
                    print(f"  ⚠️  Failed: {recipe.title[:40]} — {e}")
            await session.commit()

        print(f"  ✅ Stored {stored} structured recipes")
        async with async_session() as session:
            repo = RecipeRepository(session)
            total = await repo.count()
            print(f"  📦 Total recipes in DB: {total}")

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
