"""Live test: scrape Reddit for recipes using the public API."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.scrapers.reddit_public import RedditPublicScraper


async def main():
    scraper = RedditPublicScraper()
    recipes = []

    print("🔍 Scraping Reddit for recipes (limit: 10)...\n")

    async for raw_post in scraper.discover_recipes(
        hashtags=["fitmeals", "EatCheapAndHealthy", "Volumeeating"],
        limit=10,
    ):
        data = await scraper.extract_recipe_data(raw_post)
        recipes.append(data)
        print(f"  ✅ [{data['subreddit']}] {data['title'][:70]}")
        print(f"     👍 {data['likes']} | 💬 {data['comments']} | by u/{data['author']}")
        print()

    await scraper.close()

    print(f"\n📊 Total recipes found: {len(recipes)}")
    if recipes:
        print(f"🏆 Top post: {recipes[0]['title'][:80]}")
        print(f"   URL: {recipes[0]['source_url']}")


if __name__ == "__main__":
    asyncio.run(main())
