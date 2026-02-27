"""Unified Recipe Orchestrator — master coordinator for multi-platform harvest.

Runs YouTube, Instagram, and TikTok discovery in parallel, extracts recipes
via AI, deduplicates, quality-scores, and stores to database.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.models import Recipe, Platform
from src.services.deduplicator import RecipeDeduplicator, DedupLog
from src.services.quality_scorer import score_recipe, QualityReport
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class HarvestStats:
    """Statistics from a single harvest run."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed

    # Per-platform counts
    discovered: dict[str, int] = field(default_factory=lambda: {"youtube": 0, "instagram": 0, "tiktok": 0})
    extracted: dict[str, int] = field(default_factory=lambda: {"youtube": 0, "instagram": 0, "tiktok": 0})
    errors: dict[str, list[str]] = field(default_factory=lambda: {"youtube": [], "instagram": [], "tiktok": []})

    # Aggregate
    total_discovered: int = 0
    total_extracted: int = 0
    duplicates_found: int = 0
    quality_passed: int = 0
    quality_failed: int = 0
    stored: int = 0

    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds(),
            "discovered": self.discovered,
            "extracted": self.extracted,
            "total_discovered": self.total_discovered,
            "total_extracted": self.total_extracted,
            "duplicates_found": self.duplicates_found,
            "quality_passed": self.quality_passed,
            "quality_failed": self.quality_failed,
            "stored": self.stored,
            "errors": {k: len(v) for k, v in self.errors.items()},
        }


class RecipeOrchestrator:
    """Master coordinator that runs all platform scrapers and manages the pipeline."""

    def __init__(
        self,
        youtube_api_key: str | None = None,
        tiktok_api_key: str | None = None,
        tiktok_api_base: str | None = None,
        instagram_api_key: str | None = None,
        instagram_api_base: str | None = None,
        anthropic_api_key: str | None = None,
        min_quality_score: float = 0.4,
    ):
        self.youtube_api_key = youtube_api_key
        self.tiktok_api_key = tiktok_api_key
        self.tiktok_api_base = tiktok_api_base
        self.instagram_api_key = instagram_api_key
        self.instagram_api_base = instagram_api_base
        self.anthropic_api_key = anthropic_api_key
        self.min_quality_score = min_quality_score

        self.deduplicator = RecipeDeduplicator()
        self._last_harvest: Optional[HarvestStats] = None

    @property
    def last_harvest(self) -> Optional[HarvestStats]:
        return self._last_harvest

    async def run_harvest(
        self,
        limit_per_platform: int = 50,
        platforms: list[str] | None = None,
    ) -> HarvestStats:
        """Run a full harvest across all configured platforms.

        1. Discover content in parallel across platforms
        2. Extract recipes via AI
        3. Deduplicate across platforms
        4. Quality score and filter
        5. Store to database

        Returns HarvestStats with full breakdown.
        """
        stats = HarvestStats()
        stats.started_at = datetime.now(timezone.utc)
        stats.status = "running"
        self._last_harvest = stats

        target_platforms = platforms or ["youtube", "instagram", "tiktok"]

        try:
            # Step 1: Parallel discovery
            logger.info(f"[harvest:{stats.run_id}] Starting discovery on {target_platforms}")
            discovery_tasks = []
            for platform in target_platforms:
                discovery_tasks.append(
                    self._discover_platform(platform, limit_per_platform, stats)
                )
            platform_results = await asyncio.gather(*discovery_tasks, return_exceptions=True)

            # Flatten raw posts
            all_raw: list[tuple[str, dict]] = []  # (platform, raw_data)
            for i, result in enumerate(platform_results):
                platform = target_platforms[i]
                if isinstance(result, Exception):
                    stats.errors[platform].append(str(result))
                    logger.error(f"[harvest:{stats.run_id}] {platform} discovery failed: {result}")
                elif isinstance(result, list):
                    all_raw.extend(result)

            stats.total_discovered = sum(stats.discovered.values())
            logger.info(f"[harvest:{stats.run_id}] Discovered {stats.total_discovered} posts")

            # Step 2: Extract recipes via AI
            logger.info(f"[harvest:{stats.run_id}] Extracting recipes...")
            all_recipes = await self._extract_all(all_raw, stats)
            stats.total_extracted = len(all_recipes)
            logger.info(f"[harvest:{stats.run_id}] Extracted {stats.total_extracted} recipes")

            # Step 3: Deduplicate (within batch + against existing DB)
            logger.info(f"[harvest:{stats.run_id}] Deduplicating...")
            deduped = await self._deduplicate(all_recipes, stats)

            # Step 4: Quality scoring
            logger.info(f"[harvest:{stats.run_id}] Quality scoring...")
            quality_recipes = self._quality_filter(deduped, stats)

            # Step 5: Store to database
            logger.info(f"[harvest:{stats.run_id}] Storing {len(quality_recipes)} recipes...")
            stats.stored = await self._store_recipes(quality_recipes)

            stats.status = "completed"
        except Exception as e:
            stats.status = "failed"
            logger.exception(f"[harvest:{stats.run_id}] Harvest failed: {e}")
        finally:
            stats.finished_at = datetime.now(timezone.utc)
            logger.info(
                f"[harvest:{stats.run_id}] Finished in {stats.duration_seconds():.1f}s — "
                f"stored={stats.stored}, discovered={stats.total_discovered}, "
                f"extracted={stats.total_extracted}, dupes={stats.duplicates_found}"
            )

        return stats

    async def _discover_platform(
        self, platform: str, limit: int, stats: HarvestStats
    ) -> list[tuple[str, dict]]:
        """Discover recipes from a single platform."""
        results: list[tuple[str, dict]] = []

        if platform == "youtube" and self.youtube_api_key:
            from src.scrapers.youtube import YouTubeScraper
            scraper = YouTubeScraper(self.youtube_api_key)
            async for post in scraper.discover_recipes(limit=limit):
                results.append(("youtube", post))
            stats.discovered["youtube"] = len(results)

        elif platform == "instagram" and self.instagram_api_key:
            from src.scrapers.instagram import InstagramScraper
            scraper = InstagramScraper(self.instagram_api_key, self.instagram_api_base)
            async for post in scraper.discover_recipes(limit=limit):
                results.append(("instagram", post))
            await scraper.close()
            stats.discovered["instagram"] = len(results)

        elif platform == "tiktok" and self.tiktok_api_key:
            from src.scrapers.tiktok import TikTokScraper
            scraper = TikTokScraper(self.tiktok_api_key, self.tiktok_api_base)
            async for post in scraper.discover_recipes(limit=limit):
                results.append(("tiktok", post))
            await scraper.close()
            stats.discovered["tiktok"] = len(results)

        else:
            logger.warning(f"[harvest] Platform {platform} not configured (missing API key)")

        return results

    async def _extract_all(
        self, raw_posts: list[tuple[str, dict]], stats: HarvestStats
    ) -> list[Recipe]:
        """Extract structured recipes from raw posts using AI."""
        if not self.anthropic_api_key:
            logger.warning("[harvest] No Anthropic API key — using local extraction only")
            return await self._extract_local(raw_posts, stats)

        from src.services.recipe_extractor import RecipeExtractor
        extractor = RecipeExtractor(self.anthropic_api_key)
        recipes: list[Recipe] = []

        # Process in batches to avoid rate limits
        batch_size = 5
        for i in range(0, len(raw_posts), batch_size):
            batch = raw_posts[i:i + batch_size]
            tasks = []
            for platform, raw in batch:
                raw["platform"] = platform
                tasks.append(extractor.extract(raw))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(results):
                platform = batch[j][0]
                if isinstance(result, Exception):
                    stats.errors[platform].append(str(result))
                elif result is not None:
                    if not result.id:
                        result.id = str(uuid.uuid4())
                    recipes.append(result)
                    stats.extracted[platform] = stats.extracted.get(platform, 0) + 1

        return recipes

    async def _extract_local(
        self, raw_posts: list[tuple[str, dict]], stats: HarvestStats
    ) -> list[Recipe]:
        """Fallback: extract recipes using local heuristics (no AI)."""
        from src.services.recipe_extractor_local import extract_recipe_local
        recipes: list[Recipe] = []
        for platform, raw in raw_posts:
            raw["platform"] = platform
            try:
                recipe = extract_recipe_local(raw)
                if recipe:
                    if not recipe.id:
                        recipe.id = str(uuid.uuid4())
                    recipes.append(recipe)
                    stats.extracted[platform] = stats.extracted.get(platform, 0) + 1
            except Exception as e:
                stats.errors[platform].append(str(e))
        return recipes

    async def _deduplicate(
        self, recipes: list[Recipe], stats: HarvestStats
    ) -> list[Recipe]:
        """Deduplicate within batch and against existing DB recipes."""
        # First: deduplicate within the batch itself
        batch_deduped = self.deduplicator.deduplicate_batch(recipes)

        # Then: check against existing DB recipes
        try:
            from src.db.engine import async_session
            from src.db.repository import RecipeRepository

            async with async_session() as session:
                repo = RecipeRepository(session)
                existing = await repo.list_recipes(limit=500)  # recent recipes for dedup

            final: list[Recipe] = []
            for recipe in batch_deduped:
                result = self.deduplicator.check(recipe, existing)
                if not result.is_duplicate:
                    final.append(recipe)
                elif result.kept_version == "new":
                    final.append(recipe)  # Will upsert
        except Exception as e:
            logger.warning(f"[harvest] DB dedup check failed, using batch-only: {e}")
            final = batch_deduped

        stats.duplicates_found = self.deduplicator.log.duplicates_found
        return final

    def _quality_filter(self, recipes: list[Recipe], stats: HarvestStats) -> list[Recipe]:
        """Score and filter recipes by quality."""
        passed: list[Recipe] = []
        for recipe in recipes:
            report = score_recipe(recipe)
            if report.score >= self.min_quality_score:
                passed.append(recipe)
                stats.quality_passed += 1
            else:
                stats.quality_failed += 1
                logger.debug(f"Quality rejected: {recipe.title[:40]} (score={report.score})")
        return passed

    async def _store_recipes(self, recipes: list[Recipe]) -> int:
        """Store recipes to database, returning count stored."""
        if not recipes:
            return 0

        try:
            from src.db.engine import async_session
            from src.db.repository import RecipeRepository

            async with async_session() as session:
                repo = RecipeRepository(session)
                stored = 0
                for recipe in recipes:
                    try:
                        await repo.upsert(recipe)
                        stored += 1
                    except Exception as e:
                        logger.warning(f"Failed to store recipe '{recipe.title[:40]}': {e}")
                await session.commit()
            return stored
        except Exception as e:
            logger.error(f"[harvest] Database storage failed: {e}")
            return 0

    @staticmethod
    def from_settings() -> RecipeOrchestrator:
        """Create an orchestrator from application settings."""
        return RecipeOrchestrator(
            youtube_api_key=settings.YOUTUBE_API_KEY,
            tiktok_api_key=settings.TIKTOK_API_KEY,
            tiktok_api_base=getattr(settings, "TIKTOK_API_BASE", None),
            instagram_api_key=settings.INSTAGRAM_API_KEY,
            instagram_api_base=getattr(settings, "INSTAGRAM_API_BASE", None),
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
        )
