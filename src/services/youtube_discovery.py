"""
YouTube Discovery Service - Find fitness recipe videos via YouTube Data API v3.

Searches for single-recipe fitness/bodybuilding videos, filters out compilations,
and returns 50-100 video URLs per run for automated extraction.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# Search queries rotated across runs for variety
SEARCH_QUERIES = [
    "high protein meal prep recipe",
    "fitness recipe easy",
    "bodybuilding meal recipe",
    "macro friendly recipe",
    "high protein dinner recipe",
    "healthy meal prep recipe macros",
    "low calorie high protein recipe",
    "anabolic recipe",
    "protein packed meal",
    "healthy bodybuilding recipe",
    "high protein breakfast recipe",
    "high protein lunch recipe",
    "macro meal prep easy",
    "protein recipe simple",
    "gym meal recipe",
]

# Patterns that indicate multi-recipe / compilation videos (skip these)
MULTI_RECIPE_PATTERNS = [
    r"\b\d+\s+(?:easy\s+)?(?:meals?|recipes?|dishes?|ideas?|options?|ways?)\b",
    r"\bfull\s+(?:day|week)\s+of\s+eating\b",
    r"\bwhat\s+i\s+eat\s+in\s+a\s+(?:day|week)\b",
    r"\bmeal\s+prep\s+for\s+the\s+week\b",
    r"\b(?:grocery|food)\s+haul\b",
    r"\btop\s+\d+\b",
    r"\b\d+\s+minute\s+meals?\b",  # "5 minute meals" = usually compilation
]

# Minimum video duration (seconds) - skip shorts/reels under 60s
MIN_DURATION_SECONDS = 60
# Maximum duration - skip 30+ min compilations
MAX_DURATION_SECONDS = 1800

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


@dataclass
class DiscoveredVideo:
    """A YouTube video discovered for recipe extraction."""
    video_id: str
    title: str
    channel_title: str
    thumbnail_url: str
    published_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class DiscoveryResult:
    """Result of a discovery run."""
    videos: list[DiscoveredVideo] = field(default_factory=list)
    total_searched: int = 0
    filtered_multi_recipe: int = 0
    filtered_duration: int = 0
    queries_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _is_multi_recipe(title: str) -> bool:
    """Check if video title suggests multiple recipes."""
    for pattern in MULTI_RECIPE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False


def _parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration (PT1H2M3S) to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeDiscoveryService:
    """Discover fitness recipe videos from YouTube."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY is required for YouTube Discovery")

    async def discover(
        self,
        max_videos: int = 100,
        queries: Optional[list[str]] = None,
        published_after: Optional[datetime] = None,
    ) -> DiscoveryResult:
        """
        Search YouTube for single-recipe fitness videos.

        Args:
            max_videos: Target number of videos to return (50-100)
            queries: Custom search queries (defaults to SEARCH_QUERIES)
            published_after: Only find videos published after this date

        Returns:
            DiscoveryResult with filtered, deduplicated video list
        """
        queries = queries or SEARCH_QUERIES
        result = DiscoveryResult()
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for query in queries:
                if len(result.videos) >= max_videos:
                    break

                result.queries_used.append(query)

                try:
                    videos = await self._search_query(
                        client, query, published_after=published_after
                    )
                    result.total_searched += len(videos)

                    for video in videos:
                        if len(result.videos) >= max_videos:
                            break
                        if video.video_id in seen_ids:
                            continue
                        seen_ids.add(video.video_id)

                        # Filter multi-recipe compilations
                        if _is_multi_recipe(video.title):
                            result.filtered_multi_recipe += 1
                            continue

                        result.videos.append(video)

                except Exception as e:
                    error_msg = f"Search failed for '{query}': {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            # Enrich with duration/view counts and filter
            if result.videos:
                result = await self._enrich_and_filter(client, result)

        logger.info(
            f"Discovery complete: {len(result.videos)} videos from "
            f"{result.total_searched} searched, "
            f"{result.filtered_multi_recipe} multi-recipe filtered, "
            f"{result.filtered_duration} duration filtered"
        )
        return result

    async def _search_query(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int = 15,
        published_after: Optional[datetime] = None,
    ) -> list[DiscoveredVideo]:
        """Execute a single YouTube search query."""
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": "relevance",
            "videoDuration": "medium",  # 4-20 minutes
            "key": self.api_key,
        }

        if published_after:
            params["publishedAfter"] = published_after.strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        videos = []
        for item in data.get("items", []):
            snippet = item["snippet"]
            video_id = item["id"].get("videoId")
            if not video_id:
                continue

            published_at = None
            if pub := snippet.get("publishedAt"):
                try:
                    published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    pass

            thumb = snippet.get("thumbnails", {}).get("high", {}).get("url", "")

            videos.append(DiscoveredVideo(
                video_id=video_id,
                title=snippet.get("title", ""),
                channel_title=snippet.get("channelTitle", ""),
                thumbnail_url=thumb,
                published_at=published_at,
            ))

        return videos

    async def _enrich_and_filter(
        self, client: httpx.AsyncClient, result: DiscoveryResult
    ) -> DiscoveryResult:
        """Fetch video details (duration, views) and filter by duration."""
        # Batch in groups of 50 (API limit)
        all_videos = result.videos
        enriched = []

        for i in range(0, len(all_videos), 50):
            batch = all_videos[i : i + 50]
            ids = ",".join(v.video_id for v in batch)

            try:
                resp = await client.get(
                    YOUTUBE_VIDEOS_URL,
                    params={
                        "part": "contentDetails,statistics",
                        "id": ids,
                        "key": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                details_map = {}
                for item in data.get("items", []):
                    vid = item["id"]
                    duration = _parse_duration(
                        item.get("contentDetails", {}).get("duration", "PT0S")
                    )
                    views = int(item.get("statistics", {}).get("viewCount", 0))
                    details_map[vid] = (duration, views)

                for video in batch:
                    if video.video_id in details_map:
                        dur, views = details_map[video.video_id]
                        video.duration_seconds = dur
                        video.view_count = views

                        if dur < MIN_DURATION_SECONDS or dur > MAX_DURATION_SECONDS:
                            result.filtered_duration += 1
                            continue

                    enriched.append(video)

            except Exception as e:
                logger.error(f"Failed to enrich batch: {e}")
                enriched.extend(batch)  # Keep un-enriched rather than drop

        result.videos = enriched
        return result
