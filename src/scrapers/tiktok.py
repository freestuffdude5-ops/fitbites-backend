"""TikTok scraper using 3rd-party API (EnsembleData or similar)."""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Default hashtags for recipe discovery on TikTok
DEFAULT_HASHTAGS = [
    "highproteinrecipe", "lowcalorierecipe", "healthyrecipe",
    "mealprep", "anabolicrecipe", "proteinrecipe",
    "caloriedeficit", "healthyfood", "fitfood",
]


class TikTokScraper(BaseScraper):
    """Scrape TikTok for viral healthy recipe videos.

    Uses a 3rd-party API (e.g. EnsembleData, Apify, or RapidAPI TikTok endpoints)
    since TikTok's official API is restrictive for content scraping.

    Set TIKTOK_API_KEY and TIKTOK_API_BASE in environment.
    """

    platform = "tiktok"

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base or "https://ensembledata.com/apis"
        self.client = httpx.AsyncClient(timeout=30)

    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Discover TikTok videos by hashtag search."""
        if not self.api_key:
            logger.warning("[tiktok] No API key configured — skipping")
            return

        tags = hashtags or DEFAULT_HASHTAGS
        per_tag = max(1, limit // len(tags))

        for tag in tags:
            try:
                resp = await self.client.get(
                    f"{self.api_base}/tt/hashtag/posts",
                    params={
                        "name": tag,
                        "count": per_tag,
                        "token": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                posts = data.get("data", [])
                for post in posts[:per_tag]:
                    yield post
            except Exception as e:
                logger.warning(f"[tiktok] Failed to fetch hashtag '{tag}': {e}")
                continue

    async def close(self):
        await self.client.aclose()

    async def extract_recipe_data(self, raw_post: dict) -> dict:
        """Extract structured data from a TikTok post for AI processing."""
        # EnsembleData format — adjust field paths for your chosen API
        desc = raw_post.get("desc", "") or raw_post.get("description", "")
        author = raw_post.get("author", {})
        stats = raw_post.get("stats", {})
        video = raw_post.get("video", {})

        author_name = (
            author.get("uniqueId")
            or author.get("unique_id")
            or raw_post.get("author_name", "unknown")
        )
        video_id = raw_post.get("id", "")

        return {
            "platform": "tiktok",
            "source_url": f"https://www.tiktok.com/@{author_name}/video/{video_id}",
            "title": desc[:120] if desc else "Untitled",
            "description": desc,
            "creator_name": author_name,
            "creator_url": f"https://www.tiktok.com/@{author_name}",
            "thumbnail_url": video.get("cover", "") or video.get("dynamicCover", ""),
            "views": stats.get("playCount", 0),
            "likes": stats.get("diggCount", 0) or stats.get("heartCount", 0),
            "comments": stats.get("commentCount", 0),
            "shares": stats.get("shareCount", 0),
            "created_at": raw_post.get("createTime"),
        }
