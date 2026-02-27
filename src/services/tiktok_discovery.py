"""
TikTok Discovery Service — find fitness recipe videos at scale.

Strategies:
1. yt-dlp search (ytsearch-like via TikTok)
2. Known fitness creator scraping
3. Hashtag page scraping via browser automation

No paid API key required.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

YTDLP_PATH = "/home/user/.local/bin/yt-dlp"

# Top fitness recipe hashtags on TikTok
DEFAULT_HASHTAGS = [
    "highproteinrecipes",
    "highproteinmeals",
    "fitnesstiktok",
    "mealprep",
    "anabolicrecipe",
    "proteinrecipe",
    "healthyrecipes",
    "lowcalorierecipe",
    "caloriedeficit",
    "gymfood",
    "macrofriendly",
]

# Known fitness recipe creators (high-quality content)
DEFAULT_CREATORS = [
    "faborafitness",
    "remington_james",
    "zacperna",
    "gregdoucette",
    "themealprepmanual",
    "maboroshi_cooking",
    "joshuaweissman",
    "ethanChlebowski",
]


@dataclass
class DiscoveredVideo:
    url: str
    video_id: str
    title: str = ""
    creator: str = ""
    description: str = ""
    view_count: int = 0
    like_count: int = 0
    duration: int = 0
    hashtags: list[str] = field(default_factory=list)


class TikTokDiscoveryService:
    """Discover TikTok recipe videos without a paid API."""

    def __init__(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        max_per_source: int = 10,
    ):
        self.hashtags = hashtags or DEFAULT_HASHTAGS
        self.creators = creators or DEFAULT_CREATORS
        self.max_per_source = max_per_source

    async def discover(self, limit: int = 50) -> list[DiscoveredVideo]:
        """Run all discovery strategies and return deduplicated video list."""
        videos: list[DiscoveredVideo] = []
        seen_ids: set[str] = set()

        # Strategy 1: Creator pages via yt-dlp
        creator_videos = await self._discover_from_creators(limit=limit)
        for v in creator_videos:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                videos.append(v)

        # Strategy 2: Hashtag search via yt-dlp
        if len(videos) < limit:
            hashtag_videos = await self._discover_from_hashtags(limit=limit - len(videos))
            for v in hashtag_videos:
                if v.video_id not in seen_ids:
                    seen_ids.add(v.video_id)
                    videos.append(v)

        logger.info(f"[tiktok-discovery] Discovered {len(videos)} unique videos")
        return videos[:limit]

    async def _discover_from_creators(self, limit: int = 30) -> list[DiscoveredVideo]:
        """Fetch recent videos from known fitness creators."""
        videos: list[DiscoveredVideo] = []
        per_creator = min(self.max_per_source, max(3, limit // len(self.creators)))

        tasks = [
            self._fetch_creator_videos(creator, per_creator)
            for creator in self.creators[:8]  # Limit concurrent creators
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"[tiktok-discovery] Creator fetch failed: {result}")
                continue
            videos.extend(result)

        return videos

    async def _fetch_creator_videos(self, creator: str, limit: int) -> list[DiscoveredVideo]:
        """Use yt-dlp to list recent videos from a TikTok creator."""
        url = f"https://www.tiktok.com/@{creator}"
        return await self._ytdlp_list(url, limit, creator=creator)

    async def _discover_from_hashtags(self, limit: int = 20) -> list[DiscoveredVideo]:
        """Fetch videos from hashtag pages."""
        videos: list[DiscoveredVideo] = []
        per_tag = min(self.max_per_source, max(3, limit // len(self.hashtags)))

        for tag in self.hashtags[:6]:  # Limit to avoid rate limits
            try:
                url = f"https://www.tiktok.com/tag/{tag}"
                tag_videos = await self._ytdlp_list(url, per_tag)
                videos.extend(tag_videos)
            except Exception as e:
                logger.warning(f"[tiktok-discovery] Hashtag {tag} failed: {e}")
            await asyncio.sleep(1)  # Rate limit between tags

        return videos

    async def _ytdlp_list(
        self, url: str, limit: int, creator: str = ""
    ) -> list[DiscoveredVideo]:
        """Use yt-dlp to list videos from a TikTok URL (creator or hashtag page)."""
        cmd = [
            YTDLP_PATH,
            "--no-download",
            "--print-json",
            "--no-warnings",
            "--no-check-certificates",
            "--playlist-end", str(limit),
            "--flat-playlist",
            "--extractor-args", "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com",
            url,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=45
            )

            videos: list[DiscoveredVideo] = []
            if stdout:
                for line in stdout.decode().strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        video = self._parse_ytdlp_entry(data, creator)
                        if video:
                            videos.append(video)
                    except json.JSONDecodeError:
                        continue

            return videos

        except asyncio.TimeoutError:
            logger.warning(f"[tiktok-discovery] Timeout fetching {url}")
            return []
        except Exception as e:
            logger.warning(f"[tiktok-discovery] yt-dlp error for {url}: {e}")
            return []

    def _parse_ytdlp_entry(self, data: dict, creator: str = "") -> Optional[DiscoveredVideo]:
        """Parse a yt-dlp JSON entry into a DiscoveredVideo."""
        video_id = str(data.get("id", ""))
        if not video_id:
            return None

        title = data.get("title", "") or data.get("fulltitle", "") or data.get("description", "")[:120]
        uploader = data.get("uploader", "") or data.get("creator", "") or creator
        description = data.get("description", "") or ""

        # Extract hashtags from description
        hashtags = re.findall(r"#(\w+)", description)

        # Build URL
        webpage_url = data.get("webpage_url", "")
        if not webpage_url:
            webpage_url = f"https://www.tiktok.com/@{uploader}/video/{video_id}"

        return DiscoveredVideo(
            url=webpage_url,
            video_id=video_id,
            title=title[:200],
            creator=uploader,
            description=description[:500],
            view_count=data.get("view_count", 0) or 0,
            like_count=data.get("like_count", 0) or 0,
            duration=data.get("duration", 0) or 0,
            hashtags=hashtags[:20],
        )

    def filter_recipe_videos(self, videos: list[DiscoveredVideo]) -> list[DiscoveredVideo]:
        """Filter videos likely to contain recipes based on signals."""
        recipe_keywords = {
            "recipe", "meal", "cook", "protein", "calorie", "macro",
            "ingredient", "prep", "healthy", "anabolic", "fitness",
            "breakfast", "lunch", "dinner", "snack", "dessert",
        }

        filtered = []
        for v in videos:
            text = f"{v.title} {v.description}".lower()
            tag_text = " ".join(v.hashtags).lower()
            combined = f"{text} {tag_text}"

            # Score based on keyword matches
            score = sum(1 for kw in recipe_keywords if kw in combined)

            # Duration filter: recipes are usually 15s-180s on TikTok
            if v.duration and (v.duration < 10 or v.duration > 600):
                score -= 2

            if score >= 1:
                filtered.append(v)

        # Sort by engagement
        filtered.sort(key=lambda v: v.view_count + v.like_count * 10, reverse=True)
        return filtered
