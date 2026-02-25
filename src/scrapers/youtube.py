"""YouTube scraper using official Data API v3 (free tier)."""
from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Healthy recipe channels to monitor (from IRIS research)
DEFAULT_CHANNELS = [
    # Add channel IDs after lookup
]

DEFAULT_HASHTAGS = [
    "high protein recipes",
    "low calorie recipes",
    "meal prep",
    "anabolic recipes",
    "macro friendly",
    "protein recipes",
]


class YouTubeScraper(BaseScraper):
    platform = "youtube"
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)

    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Search YouTube for recipe videos by hashtag/query."""
        queries = hashtags or DEFAULT_HASHTAGS
        seen = set()

        for query in queries:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": min(limit, 50),
                "order": "viewCount",
                "key": self.api_key,
                "videoCategoryId": "26",  # How-to & Style
            }
            resp = await self.client.get(f"{self.BASE_URL}/search", params=params)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                vid_id = item["id"]["videoId"]
                if vid_id in seen:
                    continue
                seen.add(vid_id)
                yield item

                if len(seen) >= limit:
                    return

    async def _get_video_details(self, video_ids: list[str]) -> list[dict]:
        """Fetch detailed stats for videos."""
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }
        resp = await self.client.get(f"{self.BASE_URL}/videos", params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def _get_captions(self, video_id: str) -> str | None:
        """Attempt to fetch auto-generated captions (for recipe extraction).
        Note: Requires OAuth for non-public captions. 
        Fallback: use video description."""
        # For MVP, we rely on description + title. 
        # Full caption extraction needs youtube-transcript-api or similar.
        return None

    async def extract_recipe_data(self, raw_post: dict) -> dict:
        """Extract structured data from YouTube search result."""
        snippet = raw_post.get("snippet", {})
        video_id = raw_post["id"]["videoId"]

        # Get full details
        details = await self._get_video_details([video_id])
        stats = details[0].get("statistics", {}) if details else {}

        return {
            "platform": "youtube",
            "source_url": f"https://youtube.com/watch?v={video_id}",
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url"),
            "published_at": snippet.get("publishedAt"),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        }

    async def close(self):
        await self.client.aclose()
