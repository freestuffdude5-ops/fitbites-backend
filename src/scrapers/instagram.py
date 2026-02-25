"""Instagram scraper using 3rd-party API."""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

DEFAULT_HASHTAGS = [
    "highproteinmeals", "lowcaloriemeals", "healthyrecipes",
    "mealprep", "fitmeals", "proteinpacked",
    "cleanrecipes", "macrofriendly",
]


class InstagramScraper(BaseScraper):
    """Scrape Instagram for viral healthy recipe posts/reels.

    Uses a 3rd-party API (e.g. Apify, RapidAPI Instagram endpoints).
    Set INSTAGRAM_API_KEY and INSTAGRAM_API_BASE in environment.
    """

    platform = "instagram"

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base or "https://instagram-scraper-api.p.rapidapi.com"
        self.client = httpx.AsyncClient(timeout=30)

    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Discover Instagram posts by hashtag."""
        if not self.api_key:
            logger.warning("[instagram] No API key configured — skipping")
            return

        tags = hashtags or DEFAULT_HASHTAGS
        per_tag = max(1, limit // len(tags))

        for tag in tags:
            try:
                resp = await self.client.get(
                    f"{self.api_base}/v1/hashtag",
                    params={"hashtag": tag},
                    headers={
                        "X-RapidAPI-Key": self.api_key,
                        "X-RapidAPI-Host": self.api_base.split("//")[1],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                posts = data.get("data", {}).get("items", [])
                for post in posts[:per_tag]:
                    yield post
            except Exception as e:
                logger.warning(f"[instagram] Failed to fetch hashtag '{tag}': {e}")
                continue

    async def close(self):
        await self.client.aclose()

    async def extract_recipe_data(self, raw_post: dict) -> dict:
        """Extract structured data from an Instagram post."""
        caption = raw_post.get("caption", {}) or {}
        caption_text = caption.get("text", "") if isinstance(caption, dict) else str(caption)
        user = raw_post.get("user", {})
        shortcode = raw_post.get("code", "") or raw_post.get("shortcode", "")

        username = user.get("username", "unknown")

        return {
            "platform": "instagram",
            "source_url": f"https://www.instagram.com/p/{shortcode}/" if shortcode else "",
            "title": caption_text[:120] if caption_text else "Untitled",
            "description": caption_text,
            "creator_name": username,
            "creator_url": f"https://www.instagram.com/{username}/",
            "thumbnail_url": raw_post.get("image_versions2", {}).get("candidates", [{}])[0].get("url", "")
                if raw_post.get("image_versions2") else raw_post.get("thumbnail_url", ""),
            "views": raw_post.get("play_count", 0) or raw_post.get("view_count", 0),
            "likes": raw_post.get("like_count", 0),
            "comments": raw_post.get("comment_count", 0),
            "shares": raw_post.get("reshare_count", 0),
            "created_at": raw_post.get("taken_at"),
        }
