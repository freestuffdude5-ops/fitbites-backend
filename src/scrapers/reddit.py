"""Reddit scraper using official API."""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Subreddits from IRIS research
DEFAULT_SUBREDDITS = [
    "mealprep",
    "fitmeals",
    "1200isplenty",
    "EatCheapAndHealthy",
    "MealPrepSunday",
    "HealthyFood",
    "ketorecipes",
    "veganfitness",
    "Volumeeating",
]


class RedditScraper(BaseScraper):
    platform = "reddit"
    BASE_URL = "https://oauth.reddit.com"

    def __init__(self, client_id: str, client_secret: str, user_agent: str = "FitBites/0.1"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.client = httpx.AsyncClient(timeout=30)
        self._token: str | None = None

    async def _authenticate(self):
        """Get OAuth token."""
        resp = await self.client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self.user_agent},
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self._token:
            await self._authenticate()
        resp = await self.client.get(
            f"{self.BASE_URL}{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {self._token}",
                "User-Agent": self.user_agent,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Fetch top posts from recipe subreddits."""
        subreddits = hashtags or DEFAULT_SUBREDDITS
        seen = set()

        for sub in subreddits:
            try:
                data = await self._get(
                    f"/r/{sub}/hot",
                    params={"limit": min(limit, 25)},
                )
                for post in data.get("data", {}).get("children", []):
                    post_data = post["data"]
                    if post_data["id"] in seen:
                        continue
                    # Skip non-recipe posts (basic filter)
                    if post_data.get("is_self", False) or post_data.get("url", "").endswith(
                        (".jpg", ".png", ".gif")
                    ):
                        seen.add(post_data["id"])
                        yield post_data
            except Exception as e:
                logger.warning(f"Failed to scrape r/{sub}: {e}")
                continue

    async def extract_recipe_data(self, raw_post: dict) -> dict:
        return {
            "platform": "reddit",
            "source_url": f"https://reddit.com{raw_post.get('permalink', '')}",
            "post_id": raw_post["id"],
            "title": raw_post.get("title", ""),
            "description": raw_post.get("selftext", ""),
            "author": raw_post.get("author", ""),
            "subreddit": raw_post.get("subreddit", ""),
            "thumbnail_url": raw_post.get("thumbnail")
            if raw_post.get("thumbnail", "").startswith("http")
            else None,
            "views": None,  # Reddit doesn't expose per-post views
            "likes": raw_post.get("ups", 0),
            "comments": raw_post.get("num_comments", 0),
            "published_at": raw_post.get("created_utc"),
        }

    async def close(self):
        await self.client.aclose()
