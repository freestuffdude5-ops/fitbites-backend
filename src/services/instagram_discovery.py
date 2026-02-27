"""Instagram Recipe Discovery Service.

Discovers recipe posts from fitness influencers via multiple strategies:
1. Hashtag-based discovery (public API / scraping)
2. Creator-based discovery (known fitness accounts)
3. oEmbed validation for URL enrichment

Returns 20-50 post URLs per run for downstream extraction.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Curated fitness/recipe hashtags ordered by specificity
RECIPE_HASHTAGS = [
    "highproteinrecipes",
    "proteinrecipes",
    "fitnessfood",
    "healthymeals",
    "macrofriendlyrecipes",
    "mealpreprecipes",
    "lowcaloriemeals",
    "fitmeals",
    "cleanrecipes",
    "proteinpacked",
    "anabolicrecipes",
    "gymfood",
]

# Known fitness recipe creators (username → priority)
TOP_FITNESS_CREATORS = [
    "fitmencook",
    "meowmeix",
    "themealprepmanual",
    "workweeklunch",
    "fitcouplemealprep",
    "macro.friendly.meals",
    "dailymealpreps",
    "cleanfoodcrush",
    "the.healthyish",
    "zfrancesconi",
]


@dataclass
class DiscoveredPost:
    """A discovered Instagram post candidate for extraction."""
    url: str
    shortcode: str
    source: str  # "hashtag:xyz" or "creator:xyz"
    caption_preview: str = ""
    thumbnail_url: str = ""
    like_count: int = 0
    creator_username: str = ""
    discovered_at: float = field(default_factory=time.time)

    @property
    def dedup_key(self) -> str:
        return self.shortcode


class InstagramDiscoveryService:
    """Discover Instagram recipe posts for extraction pipeline."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: str = "https://instagram-scraper-api.p.rapidapi.com",
        rate_limit_per_hour: int = 20,
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.rate_limit_per_hour = rate_limit_per_hour
        self._request_times: list[float] = []
        self.client = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self.client.aclose()

    # ── Rate Limiting ──────────────────────────────────────────

    async def _wait_for_rate_limit(self):
        """Enforce rate limiting (Instagram is strict)."""
        now = time.time()
        hour_ago = now - 3600
        self._request_times = [t for t in self._request_times if t > hour_ago]

        if len(self._request_times) >= self.rate_limit_per_hour:
            wait = self._request_times[0] - hour_ago + 1
            logger.info(f"[ig-discovery] Rate limit reached, waiting {wait:.0f}s")
            await asyncio.sleep(wait)

        self._request_times.append(time.time())

    # ── Discovery Strategies ───────────────────────────────────

    async def discover_by_hashtag(
        self,
        hashtags: list[str] | None = None,
        per_tag_limit: int = 10,
    ) -> list[DiscoveredPost]:
        """Strategy 1: Discover posts via hashtag search."""
        tags = hashtags or RECIPE_HASHTAGS[:6]
        results: list[DiscoveredPost] = []

        for tag in tags:
            await self._wait_for_rate_limit()
            try:
                posts = await self._fetch_hashtag_posts(tag, per_tag_limit)
                for post in posts:
                    results.append(self._raw_to_discovered(post, source=f"hashtag:{tag}"))
            except Exception as e:
                logger.warning(f"[ig-discovery] Hashtag '{tag}' failed: {e}")
                continue

        return results

    async def discover_by_creators(
        self,
        creators: list[str] | None = None,
        per_creator_limit: int = 5,
    ) -> list[DiscoveredPost]:
        """Strategy 2: Discover recent posts from known fitness creators."""
        usernames = creators or TOP_FITNESS_CREATORS[:5]
        results: list[DiscoveredPost] = []

        for username in usernames:
            await self._wait_for_rate_limit()
            try:
                posts = await self._fetch_creator_posts(username, per_creator_limit)
                for post in posts:
                    results.append(
                        self._raw_to_discovered(post, source=f"creator:{username}")
                    )
            except Exception as e:
                logger.warning(f"[ig-discovery] Creator '{username}' failed: {e}")
                continue

        return results

    async def discover(
        self,
        limit: int = 50,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
    ) -> list[DiscoveredPost]:
        """Run full discovery pipeline. Returns deduplicated posts."""
        all_posts: list[DiscoveredPost] = []

        # Run both strategies
        hashtag_posts = await self.discover_by_hashtag(hashtags, per_tag_limit=8)
        creator_posts = await self.discover_by_creators(creators, per_creator_limit=5)

        all_posts.extend(hashtag_posts)
        all_posts.extend(creator_posts)

        # Deduplicate by shortcode
        seen: set[str] = set()
        unique: list[DiscoveredPost] = []
        for post in all_posts:
            if post.dedup_key not in seen:
                seen.add(post.dedup_key)
                unique.append(post)

        # Filter for likely recipes
        recipe_posts = [p for p in unique if self._looks_like_recipe(p)]

        # Sort by engagement (likes), take top N
        recipe_posts.sort(key=lambda p: p.like_count, reverse=True)
        return recipe_posts[:limit]

    # ── API Calls ──────────────────────────────────────────────

    async def _fetch_hashtag_posts(self, hashtag: str, limit: int) -> list[dict]:
        """Fetch posts for a hashtag via API."""
        if not self.api_key:
            logger.debug("[ig-discovery] No API key, using oEmbed-only mode")
            return []

        resp = await self.client.get(
            f"{self.api_base}/v1/hashtag",
            params={"hashtag": hashtag},
            headers={
                "X-RapidAPI-Key": self.api_key,
                "X-RapidAPI-Host": self.api_base.split("//")[1],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        return items[:limit]

    async def _fetch_creator_posts(self, username: str, limit: int) -> list[dict]:
        """Fetch recent posts from a creator via API."""
        if not self.api_key:
            return []

        resp = await self.client.get(
            f"{self.api_base}/v1/user/posts",
            params={"username": username},
            headers={
                "X-RapidAPI-Key": self.api_key,
                "X-RapidAPI-Host": self.api_base.split("//")[1],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        return items[:limit]

    async def validate_url_via_oembed(self, url: str) -> dict | None:
        """Validate and enrich a post URL via Instagram oEmbed (no auth)."""
        try:
            resp = await self.client.get(
                f"https://api.instagram.com/oembed/?url={url}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # ── Helpers ─────────────────────────────────────────────────

    def _raw_to_discovered(self, raw: dict, source: str) -> DiscoveredPost:
        """Convert raw API response to DiscoveredPost."""
        shortcode = raw.get("code") or raw.get("shortcode", "")
        caption = raw.get("caption", {})
        caption_text = ""
        if isinstance(caption, dict):
            caption_text = caption.get("text", "")
        elif isinstance(caption, str):
            caption_text = caption

        user = raw.get("user", {})
        thumbnail = ""
        if raw.get("image_versions2"):
            candidates = raw["image_versions2"].get("candidates", [])
            if candidates:
                thumbnail = candidates[0].get("url", "")
        elif raw.get("thumbnail_url"):
            thumbnail = raw["thumbnail_url"]

        return DiscoveredPost(
            url=f"https://www.instagram.com/p/{shortcode}/" if shortcode else "",
            shortcode=shortcode,
            source=source,
            caption_preview=caption_text[:300] if caption_text else "",
            thumbnail_url=thumbnail,
            like_count=raw.get("like_count", 0) or 0,
            creator_username=user.get("username", "unknown"),
        )

    @staticmethod
    def _looks_like_recipe(post: DiscoveredPost) -> bool:
        """Heuristic filter: does this post look like it contains a recipe?"""
        text = post.caption_preview.lower()
        if not text:
            return True  # Can't tell, let extraction decide

        recipe_signals = [
            r'\b(?:recipe|ingredients?|instructions?|directions?)\b',
            r'\b(?:calories?|protein|carbs?|macros?)\b',
            r'\b(?:cook|bake|prep|blend|mix|stir|saute|grill)\b',
            r'\b(?:cups?|tbsp|tsp|oz|grams?|servings?)\b',
            r'\b(?:chicken|salmon|rice|oats|eggs?|avocado|broccoli)\b',
        ]

        matches = sum(1 for pat in recipe_signals if re.search(pat, text))
        return matches >= 2  # At least 2 recipe signals
