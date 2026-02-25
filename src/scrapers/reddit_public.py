"""Reddit scraper using public JSON API — no API keys required.

Reddit exposes .json endpoints for any subreddit. Rate limit is ~30 req/min
for unauthenticated requests. We add delays to be respectful.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)

# High-quality recipe subreddits ranked by relevance to FitBites
RECIPE_SUBREDDITS = [
    "fitmeals",
    "mealprep",
    "MealPrepSunday",
    "EatCheapAndHealthy",
    "1200isplenty",
    "1500isplenty",
    "Volumeeating",
    "HealthyFood",
    "ketorecipes",
    "veganfitness",
    "veganrecipes",
    "GifRecipes",
    "recipes",
    "Cooking",
]

# Keywords that indicate a post contains a recipe
RECIPE_KEYWORDS = re.compile(
    r"recipe|ingredient|calories|protein|macro|cook|bake|prep|"
    r"chicken|salmon|tofu|quinoa|oats|greek yogurt|"
    r"kcal|cal per|grams? of protein|high.?protein|low.?cal",
    re.IGNORECASE,
)


class RedditPublicScraper(BaseScraper):
    """Scrape Reddit for recipes using the public .json API (no auth needed)."""

    platform = "reddit"
    BASE_URL = "https://www.reddit.com"

    def __init__(self, user_agent: str = "FitBites/1.0 (Recipe Discovery App)"):
        self.user_agent = user_agent
        self.client = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )
        self._request_count = 0

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        """Fetch a Reddit .json endpoint with rate limiting."""
        self._request_count += 1
        # Respect rate limits: ~2 second delay between requests
        if self._request_count > 1:
            await asyncio.sleep(2.0)

        url = f"{self.BASE_URL}{path}.json"
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _is_recipe_post(self, post: dict) -> bool:
        """Check if a post likely contains a recipe."""
        title = post.get("title", "")
        body = post.get("selftext", "")
        text = f"{title} {body}"

        # Must have recipe-related keywords
        if not RECIPE_KEYWORDS.search(text):
            return False

        # Skip very short posts (likely just images with no recipe)
        if post.get("is_self") and len(body) < 50:
            return False

        # Skip posts with very low engagement
        score = post.get("score", 0)
        if score < 5:
            return False

        return True

    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Fetch top posts from recipe subreddits using public JSON API."""
        subreddits = hashtags or RECIPE_SUBREDDITS
        seen = set()
        total = 0

        for sub in subreddits:
            if total >= limit:
                break

            for sort in ["hot", "top"]:
                if total >= limit:
                    break

                try:
                    params = {"limit": 25}
                    if sort == "top":
                        params["t"] = "week"

                    data = await self._get_json(f"/r/{sub}/{sort}", params=params)

                    for post in data.get("data", {}).get("children", []):
                        if total >= limit:
                            break

                        post_data = post.get("data", {})
                        post_id = post_data.get("id")

                        if not post_id or post_id in seen:
                            continue

                        if not self._is_recipe_post(post_data):
                            continue

                        seen.add(post_id)
                        total += 1
                        yield post_data

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        logger.warning(f"Rate limited on r/{sub}, waiting 10s...")
                        await asyncio.sleep(10)
                    else:
                        logger.warning(f"HTTP {e.response.status_code} on r/{sub}/{sort}")
                except Exception as e:
                    logger.warning(f"Failed to scrape r/{sub}/{sort}: {e}")
                    continue

        logger.info(f"Reddit public scraper: discovered {total} recipe posts from {len(seen)} unique posts")

    async def extract_recipe_data(self, raw_post: dict) -> dict:
        """Extract structured data from a Reddit post."""
        # Get thumbnail - Reddit provides several sizes
        thumbnail = raw_post.get("thumbnail")
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = None

        # Try to get higher-res image
        preview = raw_post.get("preview", {})
        images = preview.get("images", [])
        if images:
            source = images[0].get("source", {})
            if source.get("url"):
                # Reddit HTML-encodes URLs in preview
                thumbnail = source["url"].replace("&amp;", "&")

        return {
            "platform": "reddit",
            "source_url": f"https://reddit.com{raw_post.get('permalink', '')}",
            "post_id": raw_post["id"],
            "title": raw_post.get("title", ""),
            "description": raw_post.get("selftext", ""),
            "author": raw_post.get("author", ""),
            "subreddit": raw_post.get("subreddit", ""),
            "thumbnail_url": thumbnail,
            "views": None,  # Reddit doesn't expose
            "likes": raw_post.get("ups", 0),
            "comments": raw_post.get("num_comments", 0),
            "score": raw_post.get("score", 0),
            "upvote_ratio": raw_post.get("upvote_ratio", 0),
            "published_at": raw_post.get("created_utc"),
            "url": raw_post.get("url"),  # Link posts point to external URLs
            "is_self": raw_post.get("is_self", False),
            "flair": raw_post.get("link_flair_text"),
        }

    async def close(self):
        await self.client.aclose()
