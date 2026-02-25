"""Base scraper interface for all platform scrapers."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.models import Recipe

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base for platform-specific scrapers."""

    platform: str

    @abstractmethod
    async def discover_recipes(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Discover raw posts/videos that likely contain recipes.
        Yields raw platform data dicts."""
        ...

    @abstractmethod
    async def extract_recipe_data(self, raw_post: dict) -> dict:
        """Extract structured recipe-relevant fields from a raw post.
        Returns dict ready for AI extraction."""
        ...

    async def scrape(
        self,
        hashtags: list[str] | None = None,
        creators: list[str] | None = None,
        limit: int = 50,
    ) -> AsyncIterator[dict]:
        """Full pipeline: discover → extract raw data for AI processing."""
        async for post in self.discover_recipes(hashtags, creators, limit):
            try:
                data = await self.extract_recipe_data(post)
                yield data
            except Exception as e:
                logger.warning(f"[{self.platform}] Failed to extract from post: {e}")
                continue
