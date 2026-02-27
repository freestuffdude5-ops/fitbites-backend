"""
Instagram Recipe Automation Pipeline.

End-to-end: Discover → Extract → Validate → Deduplicate → Save.
Designed for scheduled runs (cron/scheduler) at 10-20 posts/hour
to respect Instagram rate limits.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.services.instagram_discovery import (
    InstagramDiscoveryService,
    DiscoveredPost,
)
from src.api.instagram_extract import (
    ExtractedRecipe,
    extract_recipe_from_instagram,
)

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────

@dataclass
class AutomationConfig:
    """Configuration for the automation pipeline."""
    # Discovery
    max_discover: int = 50
    hashtags: list[str] | None = None
    creators: list[str] | None = None

    # Rate limiting
    rate_limit_per_hour: int = 15  # Conservative for Instagram
    delay_between_extractions: float = 240.0  # 4 min between extractions

    # Quality thresholds
    min_success_rate: float = 0.75  # Reject recipes below 75% completeness
    min_ingredients: int = 2
    min_instructions: int = 1

    # API
    instagram_api_key: str | None = None
    instagram_api_base: str = "https://instagram-scraper-api.p.rapidapi.com"


# ── Pipeline Result ────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Result of a single automation run."""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    discovered: int = 0
    extracted: int = 0
    passed_quality: int = 0
    duplicates_skipped: int = 0
    saved: int = 0
    errors: list[str] = field(default_factory=list)
    recipes: list[ExtractedRecipe] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    def summary(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": round(self.duration_seconds, 1),
            "discovered": self.discovered,
            "extracted": self.extracted,
            "passed_quality": self.passed_quality,
            "duplicates_skipped": self.duplicates_skipped,
            "saved": self.saved,
            "error_count": len(self.errors),
        }


# ── Deduplication ──────────────────────────────────────────────

class RecipeDeduplicator:
    """Check for duplicate recipes using URL and content hashing."""

    def __init__(self):
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()

    def load_existing_urls(self, urls: list[str]):
        """Load already-saved URLs from database."""
        self._seen_urls.update(u.rstrip("/").lower() for u in urls)

    def is_duplicate(self, recipe: ExtractedRecipe) -> bool:
        """Check if recipe is a duplicate."""
        # URL-based dedup
        url_normalized = recipe.source_url.rstrip("/").lower()
        if url_normalized in self._seen_urls:
            return True

        # Content-based dedup (title + ingredients hash)
        content_key = f"{recipe.title.lower().strip()}|{'|'.join(sorted(recipe.ingredients[:5]))}"
        content_hash = hashlib.sha256(content_key.encode()).hexdigest()[:16]
        if content_hash in self._seen_hashes:
            return True

        # Mark as seen
        self._seen_urls.add(url_normalized)
        self._seen_hashes.add(content_hash)
        return False


# ── Quality Filter ─────────────────────────────────────────────

def passes_quality_filter(recipe: ExtractedRecipe, config: AutomationConfig) -> bool:
    """Check if extracted recipe meets quality thresholds."""
    if recipe.success_rate < config.min_success_rate:
        logger.debug(
            f"Quality reject: success_rate {recipe.success_rate:.0%} < {config.min_success_rate:.0%}"
        )
        return False

    if len(recipe.ingredients) < config.min_ingredients:
        logger.debug(f"Quality reject: {len(recipe.ingredients)} ingredients < {config.min_ingredients}")
        return False

    if len(recipe.instructions) < config.min_instructions:
        logger.debug(f"Quality reject: {len(recipe.instructions)} instructions < {config.min_instructions}")
        return False

    return True


# ── Save Function (pluggable) ──────────────────────────────────

async def save_recipe_to_db(recipe: ExtractedRecipe, db_session=None) -> str | None:
    """Save extracted recipe to database. Returns recipe ID or None.

    If no db_session is provided, logs the recipe (dry-run mode).
    """
    if db_session is None:
        logger.info(f"[dry-run] Would save: {recipe.title} ({recipe.source_url})")
        return f"dry-run-{hashlib.md5(recipe.source_url.encode()).hexdigest()[:8]}"

    # Production: use the repository
    try:
        from src.db.repository import RecipeRepository
        repo = RecipeRepository(db_session)
        recipe_id = await repo.create_from_extraction(
            title=recipe.title,
            source_url=recipe.source_url,
            platform="instagram",
            creator_username=recipe.creator_username or "unknown",
            nutrition={
                "calories": recipe.nutrition.calories,
                "protein_g": recipe.nutrition.protein_grams,
                "carbs_g": recipe.nutrition.carbs_grams,
                "fat_g": recipe.nutrition.fat_grams,
            },
            ingredients=recipe.ingredients,
            instructions=[i.text for i in recipe.instructions],
            thumbnail_url=recipe.thumbnail_url,
            description=recipe.description,
        )
        return recipe_id
    except Exception as e:
        logger.error(f"Failed to save recipe: {e}")
        return None


# ── Main Pipeline ──────────────────────────────────────────────

class InstagramAutomationPipeline:
    """Orchestrates the full Instagram recipe automation."""

    def __init__(self, config: AutomationConfig | None = None):
        self.config = config or AutomationConfig()
        self.deduplicator = RecipeDeduplicator()
        self._discovery: InstagramDiscoveryService | None = None

    async def _get_discovery(self) -> InstagramDiscoveryService:
        if not self._discovery:
            self._discovery = InstagramDiscoveryService(
                api_key=self.config.instagram_api_key,
                api_base=self.config.instagram_api_base,
                rate_limit_per_hour=self.config.rate_limit_per_hour,
            )
        return self._discovery

    async def run(
        self,
        db_session=None,
        existing_urls: list[str] | None = None,
        max_extract: int | None = None,
    ) -> PipelineResult:
        """Execute full automation pipeline.

        Args:
            db_session: Database session for saving (None = dry-run).
            existing_urls: Already-saved URLs to skip.
            max_extract: Override max extractions per run.
        """
        result = PipelineResult()

        # Load existing URLs for dedup
        if existing_urls:
            self.deduplicator.load_existing_urls(existing_urls)

        # Phase 1: Discover
        logger.info("[pipeline] Phase 1: Discovering Instagram recipe posts...")
        discovery = await self._get_discovery()
        try:
            posts = await discovery.discover(
                limit=self.config.max_discover,
                hashtags=self.config.hashtags,
                creators=self.config.creators,
            )
            result.discovered = len(posts)
            logger.info(f"[pipeline] Discovered {len(posts)} candidate posts")
        except Exception as e:
            result.errors.append(f"Discovery failed: {e}")
            logger.error(f"[pipeline] Discovery failed: {e}")
            result.finished_at = datetime.now(timezone.utc)
            return result

        # Phase 2: Extract + Validate + Save
        extract_limit = max_extract or self.config.rate_limit_per_hour
        extracted_count = 0

        for i, post in enumerate(posts):
            if extracted_count >= extract_limit:
                logger.info(f"[pipeline] Rate limit reached ({extract_limit}), stopping")
                break

            logger.info(
                f"[pipeline] Extracting {i+1}/{len(posts)}: {post.url}"
            )

            try:
                recipe = await extract_recipe_from_instagram(post.url)
                result.extracted += 1
                extracted_count += 1
            except Exception as e:
                result.errors.append(f"Extract failed ({post.url}): {e}")
                logger.warning(f"[pipeline] Extraction failed: {e}")
                continue

            # Quality check
            if not passes_quality_filter(recipe, self.config):
                logger.info(
                    f"[pipeline] Quality filter rejected: {recipe.title} "
                    f"(rate={recipe.success_rate:.0%})"
                )
                continue
            result.passed_quality += 1

            # Dedup check
            if self.deduplicator.is_duplicate(recipe):
                result.duplicates_skipped += 1
                logger.info(f"[pipeline] Duplicate skipped: {recipe.source_url}")
                continue

            # Save
            recipe_id = await save_recipe_to_db(recipe, db_session)
            if recipe_id:
                result.saved += 1
                result.recipes.append(recipe)
                logger.info(f"[pipeline] Saved: {recipe.title} (id={recipe_id})")

            # Rate limiting delay
            if extracted_count < extract_limit and i < len(posts) - 1:
                delay = self.config.delay_between_extractions
                logger.debug(f"[pipeline] Rate limit delay: {delay}s")
                await asyncio.sleep(delay)

        result.finished_at = datetime.now(timezone.utc)
        logger.info(
            f"[pipeline] Complete: {result.saved} saved, "
            f"{result.extracted} extracted, {result.discovered} discovered "
            f"({result.duration_seconds:.0f}s)"
        )
        return result

    async def close(self):
        if self._discovery:
            await self._discovery.close()


# ── Convenience runner ─────────────────────────────────────────

async def run_instagram_automation(
    config: AutomationConfig | None = None,
    db_session=None,
    existing_urls: list[str] | None = None,
) -> PipelineResult:
    """Convenience function to run the full pipeline."""
    pipeline = InstagramAutomationPipeline(config)
    try:
        return await pipeline.run(db_session, existing_urls)
    finally:
        await pipeline.close()
