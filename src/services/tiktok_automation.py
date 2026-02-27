"""
TikTok Recipe Automation Pipeline

Full pipeline: discover → extract → validate → deduplicate → save.
Designed for scheduled runs (e.g., every 6 hours via scheduler).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.services.tiktok_discovery import TikTokDiscoveryService, DiscoveredVideo
from src.api.tiktok_extract import extract_recipe_from_tiktok, ExtractedRecipe

logger = logging.getLogger(__name__)

# Persistent dedup store
DEDUP_FILE = Path(__file__).parent.parent.parent / "data" / "tiktok_seen_ids.json"
RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "tiktok_results"


@dataclass
class PipelineConfig:
    """Configuration for the automation pipeline."""
    discovery_limit: int = 50
    min_success_rate: float = 0.40  # Minimum extraction quality (40% = ~3/7 fields)
    rate_limit_delay: float = 2.0   # Seconds between extractions
    max_extraction_errors: int = 5  # Stop after N consecutive errors
    max_videos_per_run: int = 30    # Cap per run to avoid abuse
    save_results: bool = True
    hashtags: list[str] | None = None
    creators: list[str] | None = None


@dataclass
class PipelineResult:
    """Summary of a pipeline run."""
    discovered: int = 0
    filtered: int = 0
    extracted: int = 0
    passed_quality: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    recipes: list[ExtractedRecipe] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: str = ""

    def summary(self) -> str:
        return (
            f"TikTok Pipeline Run ({self.timestamp})\n"
            f"  Discovered: {self.discovered}\n"
            f"  Filtered (recipe-like): {self.filtered}\n"
            f"  Duplicates skipped: {self.duplicates_skipped}\n"
            f"  Extracted: {self.extracted}\n"
            f"  Passed quality (≥{int(0.4*100)}%): {self.passed_quality}\n"
            f"  Errors: {self.errors}\n"
            f"  Duration: {self.duration_seconds:.1f}s"
        )


class TikTokAutomationPipeline:
    """End-to-end TikTok recipe extraction pipeline."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self._seen_ids: set[str] = set()
        self._load_seen_ids()

    def _load_seen_ids(self):
        """Load previously seen video IDs from disk."""
        if DEDUP_FILE.exists():
            try:
                data = json.loads(DEDUP_FILE.read_text())
                self._seen_ids = set(data.get("seen_ids", []))
                logger.info(f"[tiktok-pipeline] Loaded {len(self._seen_ids)} seen IDs")
            except Exception:
                self._seen_ids = set()

    def _save_seen_ids(self):
        """Persist seen IDs to disk."""
        DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "seen_ids": list(self._seen_ids),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "count": len(self._seen_ids),
        }
        DEDUP_FILE.write_text(json.dumps(data, indent=2))

    def _video_hash(self, url: str) -> str:
        """Generate dedup key from URL."""
        # Extract video ID from URL
        import re
        m = re.search(r"/video/(\d+)", url)
        if m:
            return m.group(1)
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _is_duplicate(self, video: DiscoveredVideo) -> bool:
        """Check if we've already processed this video."""
        return video.video_id in self._seen_ids or self._video_hash(video.url) in self._seen_ids

    def _mark_seen(self, video: DiscoveredVideo):
        """Mark a video as processed."""
        self._seen_ids.add(video.video_id)
        self._seen_ids.add(self._video_hash(video.url))

    async def run(self) -> PipelineResult:
        """Execute full pipeline: discover → extract → validate → save."""
        start = time.time()
        result = PipelineResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # ── Step 1: Discover ───────────────────────────────────────────
        logger.info("[tiktok-pipeline] Step 1: Discovering videos...")
        discovery = TikTokDiscoveryService(
            hashtags=self.config.hashtags,
            creators=self.config.creators,
        )
        all_videos = await discovery.discover(limit=self.config.discovery_limit)
        result.discovered = len(all_videos)

        # ── Step 2: Filter recipe-like ─────────────────────────────────
        recipe_videos = discovery.filter_recipe_videos(all_videos)
        result.filtered = len(recipe_videos)
        logger.info(f"[tiktok-pipeline] Step 2: {result.filtered}/{result.discovered} look like recipes")

        # ── Step 3: Deduplicate ────────────────────────────────────────
        new_videos: list[DiscoveredVideo] = []
        for v in recipe_videos:
            if self._is_duplicate(v):
                result.duplicates_skipped += 1
            else:
                new_videos.append(v)

        new_videos = new_videos[: self.config.max_videos_per_run]
        logger.info(
            f"[tiktok-pipeline] Step 3: {len(new_videos)} new videos "
            f"({result.duplicates_skipped} duplicates skipped)"
        )

        # ── Step 4: Extract ────────────────────────────────────────────
        consecutive_errors = 0

        for i, video in enumerate(new_videos):
            if consecutive_errors >= self.config.max_extraction_errors:
                logger.warning("[tiktok-pipeline] Too many consecutive errors, stopping")
                break

            logger.info(f"[tiktok-pipeline] Extracting {i+1}/{len(new_videos)}: {video.url}")

            try:
                recipe = await asyncio.get_event_loop().run_in_executor(
                    None, extract_recipe_from_tiktok, video.url
                )
                result.extracted += 1
                consecutive_errors = 0

                # ── Step 5: Quality filter ─────────────────────────────
                if recipe.success_rate >= self.config.min_success_rate:
                    result.passed_quality += 1
                    result.recipes.append(recipe)
                    logger.info(
                        f"  ✓ {recipe.title[:60]} "
                        f"(quality: {recipe.success_rate:.0%})"
                    )
                else:
                    logger.info(
                        f"  ✗ Low quality ({recipe.success_rate:.0%}), skipping"
                    )

                self._mark_seen(video)

            except Exception as e:
                result.errors += 1
                consecutive_errors += 1
                logger.warning(f"  ✗ Error: {e}")
                self._mark_seen(video)  # Don't retry failures

            # Rate limit
            await asyncio.sleep(self.config.rate_limit_delay)

        # ── Step 6: Save ───────────────────────────────────────────────
        if self.config.save_results and result.recipes:
            self._save_results(result)

        self._save_seen_ids()

        result.duration_seconds = time.time() - start
        logger.info(f"[tiktok-pipeline] Complete!\n{result.summary()}")

        return result

    def _save_results(self, result: PipelineResult):
        """Save extracted recipes to disk."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_file = RESULTS_DIR / f"run_{ts}.json"

        data = {
            "timestamp": result.timestamp,
            "summary": {
                "discovered": result.discovered,
                "filtered": result.filtered,
                "extracted": result.extracted,
                "passed_quality": result.passed_quality,
                "duplicates_skipped": result.duplicates_skipped,
                "errors": result.errors,
                "duration_seconds": result.duration_seconds,
            },
            "recipes": [r.model_dump() for r in result.recipes],
        }

        output_file.write_text(json.dumps(data, indent=2, default=str))
        logger.info(f"[tiktok-pipeline] Saved {len(result.recipes)} recipes to {output_file}")


# ── Convenience entry point ────────────────────────────────────────────────

async def run_tiktok_pipeline(
    discovery_limit: int = 50,
    min_quality: float = 0.40,
    **kwargs,
) -> PipelineResult:
    """Convenience function to run the pipeline with defaults."""
    config = PipelineConfig(
        discovery_limit=discovery_limit,
        min_success_rate=min_quality,
        **kwargs,
    )
    pipeline = TikTokAutomationPipeline(config)
    return await pipeline.run()
