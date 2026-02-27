"""
Automated Recipe Extraction Pipeline

Takes discovered YouTube videos, extracts recipes via the existing extraction
endpoint logic, validates quality, deduplicates, and saves to database.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.youtube_extract import extract_recipe_from_youtube, ExtractedRecipe
from src.db.engine import async_session
from src.db.tables import RecipeRow
from src.db.repository import RecipeRepository
from src.models import Recipe, Creator, NutritionInfo, Ingredient, Platform
from src.services.youtube_discovery import DiscoveredVideo

logger = logging.getLogger(__name__)

# Quality thresholds
MIN_SUCCESS_RATE = 0.75  # 6+ out of 8 fields
REQUIRED_FIELDS = ["title", "calories", "protein", "thumbnail", "channel", "ingredients", "instructions"]
CALORIE_MIN = 100
CALORIE_MAX = 2000
PROTEIN_MIN = 10.0
PROTEIN_MAX = 200.0


@dataclass
class ExtractionStats:
    """Statistics for a pipeline run."""
    total_videos: int = 0
    extracted: int = 0
    passed_quality: int = 0
    duplicates_skipped: int = 0
    saved: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.saved / self.total_videos if self.total_videos > 0 else 0.0

    def summary(self) -> dict:
        return {
            "total_videos": self.total_videos,
            "extracted": self.extracted,
            "passed_quality": self.passed_quality,
            "duplicates_skipped": self.duplicates_skipped,
            "saved": self.saved,
            "failed": self.failed,
            "success_rate": round(self.success_rate, 3),
            "error_count": len(self.errors),
        }


def validate_recipe(recipe: ExtractedRecipe) -> tuple[bool, Optional[str]]:
    """
    Validate extracted recipe meets quality standards.

    Returns (is_valid, rejection_reason)
    """
    # Check success rate
    if recipe.success_rate < MIN_SUCCESS_RATE:
        return False, f"Low success rate: {recipe.success_rate:.0%} (need ≥75%)"

    # Required: title
    if not recipe.title or len(recipe.title.strip()) < 3:
        return False, "Missing or too short title"

    # Required: nutrition
    if not recipe.nutrition or recipe.nutrition.calories is None:
        return False, "Missing calories"

    if recipe.nutrition.protein_grams is None:
        return False, "Missing protein"

    # Calorie range
    if recipe.nutrition.calories < CALORIE_MIN or recipe.nutrition.calories > CALORIE_MAX:
        return False, f"Calories out of range: {recipe.nutrition.calories} (need {CALORIE_MIN}-{CALORIE_MAX})"

    # Protein range
    if recipe.nutrition.protein_grams < PROTEIN_MIN or recipe.nutrition.protein_grams > PROTEIN_MAX:
        return False, f"Protein out of range: {recipe.nutrition.protein_grams}g (need {PROTEIN_MIN}-{PROTEIN_MAX}g)"

    # Required: thumbnail
    if not recipe.thumbnail_url:
        return False, "Missing thumbnail"

    # Required: channel
    if not recipe.channel_name:
        return False, "Missing channel name"

    # Required: ingredients
    if not recipe.ingredients or len(recipe.ingredients) == 0:
        return False, "Missing ingredients"

    # Required: instructions
    if not recipe.instructions or len(recipe.instructions) == 0:
        return False, "Missing instructions"

    return True, None


def _extracted_to_recipe_model(extracted: ExtractedRecipe, video: DiscoveredVideo) -> Recipe:
    """Convert ExtractedRecipe + DiscoveredVideo to our Recipe Pydantic model."""
    # Build ingredients list
    ingredients = []
    for ing_str in extracted.ingredients:
        ingredients.append(Ingredient(name=ing_str, quantity=""))

    # Build steps list
    steps = [inst.text for inst in extracted.instructions]

    # Build nutrition
    nutrition = None
    if extracted.nutrition:
        nutrition = NutritionInfo(
            calories=extracted.nutrition.calories or 0,
            protein_g=extracted.nutrition.protein_grams or 0,
            carbs_g=extracted.nutrition.carbs_grams or 0,
            fat_g=extracted.nutrition.fat_grams or 0,
            servings=1,
        )

    return Recipe(
        id=str(uuid.uuid4()),
        title=extracted.title,
        description=f"Recipe from {extracted.channel_name or video.channel_title} on YouTube",
        creator=Creator(
            username=extracted.channel_name or video.channel_title,
            display_name=extracted.channel_name or video.channel_title,
            platform=Platform.YOUTUBE,
            profile_url=f"https://www.youtube.com/@{(extracted.channel_name or video.channel_title).replace(' ', '')}",
        ),
        platform=Platform.YOUTUBE,
        source_url=extracted.source_url,
        thumbnail_url=extracted.thumbnail_url or video.thumbnail_url,
        video_url=extracted.source_url,
        ingredients=ingredients,
        steps=steps,
        nutrition=nutrition,
        tags=["high-protein"] if (nutrition and nutrition.protein_g >= 30) else [],
        views=video.view_count,
        cook_time_minutes=None,
        difficulty=None,
        virality_score=None,
        scraped_at=datetime.now(tz=timezone.utc),
        published_at=video.published_at,
    )


class RecipeAutomationPipeline:
    """Automated pipeline: extract → validate → deduplicate → save."""

    async def process_videos(self, videos: list[DiscoveredVideo]) -> ExtractionStats:
        """
        Process a list of discovered videos through the full pipeline.

        For each video:
        1. Extract recipe data via yt-dlp + transcript parsing
        2. Validate quality (required fields, ranges)
        3. Check for duplicates in database
        4. Save complete recipes
        """
        stats = ExtractionStats(total_videos=len(videos))

        async with async_session() as session:
            repo = RecipeRepository(session)

            for video in videos:
                try:
                    # Step 1: Extract
                    extracted = await self._extract_video(video)
                    if not extracted:
                        stats.failed += 1
                        continue
                    stats.extracted += 1

                    # Step 2: Validate
                    is_valid, reason = validate_recipe(extracted)
                    if not is_valid:
                        logger.debug(f"Rejected '{video.title}': {reason}")
                        stats.failed += 1
                        continue
                    stats.passed_quality += 1

                    # Step 3: Deduplicate
                    is_dup = await self._is_duplicate(session, extracted, video)
                    if is_dup:
                        logger.debug(f"Duplicate skipped: '{extracted.title}'")
                        stats.duplicates_skipped += 1
                        continue

                    # Step 4: Save
                    recipe_model = _extracted_to_recipe_model(extracted, video)
                    await repo.upsert(recipe_model)
                    await session.commit()
                    stats.saved += 1
                    logger.info(f"✅ Saved: '{extracted.title}' ({extracted.success_rate:.0%})")

                except Exception as e:
                    error_msg = f"Pipeline error for '{video.title}': {e}"
                    logger.error(error_msg)
                    stats.errors.append(error_msg)
                    stats.failed += 1
                    # Rollback on error
                    await session.rollback()

        logger.info(
            f"Pipeline complete: {stats.saved} saved, {stats.failed} failed, "
            f"{stats.duplicates_skipped} duplicates"
        )
        return stats

    async def _extract_video(self, video: DiscoveredVideo) -> Optional[ExtractedRecipe]:
        """Extract recipe from a single video. Returns None on failure."""
        try:
            # Use the existing extraction function directly (no HTTP call needed)
            recipe = extract_recipe_from_youtube(video.url)
            return recipe
        except Exception as e:
            logger.warning(f"Extraction failed for {video.video_id}: {e}")
            return None

    async def _is_duplicate(
        self,
        session: AsyncSession,
        extracted: ExtractedRecipe,
        video: DiscoveredVideo,
    ) -> bool:
        """Check if recipe already exists by source_url or similar title+calories."""
        # Check by source URL (exact match)
        stmt = select(RecipeRow).where(RecipeRow.source_url == extracted.source_url)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            return True

        # Check by similar title + same calories (fuzzy dedup)
        if extracted.nutrition and extracted.nutrition.calories:
            stmt = select(RecipeRow).where(
                and_(
                    func.lower(RecipeRow.title) == extracted.title.lower(),
                    RecipeRow.calories == extracted.nutrition.calories,
                )
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                return True

        return False
