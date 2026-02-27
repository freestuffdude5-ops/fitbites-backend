"""
Recipe Harvester - Scheduled task for daily YouTube recipe discovery + extraction.

Can be invoked via:
  - Cron job: python -m src.tasks.recipe_harvester
  - API endpoint: POST /api/v1/admin/harvest
  - Scheduler: called from src/services/scheduler.py
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config.settings import settings
from src.services.youtube_discovery import YouTubeDiscoveryService, DiscoveryResult
from src.services.recipe_automation import RecipeAutomationPipeline, ExtractionStats

logger = logging.getLogger(__name__)

# Harvest log file for tracking runs
HARVEST_LOG_DIR = Path("logs/harvester")


def _ensure_log_dir():
    HARVEST_LOG_DIR.mkdir(parents=True, exist_ok=True)


class RecipeHarvester:
    """
    Daily recipe harvester: discover YouTube videos → extract → save.

    Designed to run once daily and produce 30-100 new recipes.
    """

    def __init__(
        self,
        target_videos: int = 50,
        published_within_days: Optional[int] = 30,
    ):
        self.target_videos = target_videos
        self.published_within_days = published_within_days

    async def run(self) -> dict:
        """
        Execute a full harvest run.

        Returns summary dict with discovery + extraction stats.
        """
        run_start = datetime.now(tz=timezone.utc)
        logger.info(f"🚀 Harvest run starting at {run_start.isoformat()}")

        # Step 1: Discover videos
        discovery_result = await self._discover()

        if not discovery_result.videos:
            summary = {
                "status": "no_videos",
                "timestamp": run_start.isoformat(),
                "discovery": {
                    "total_searched": discovery_result.total_searched,
                    "videos_found": 0,
                    "errors": discovery_result.errors,
                },
                "extraction": None,
            }
            self._log_run(summary)
            logger.warning("No videos discovered. Skipping extraction.")
            return summary

        logger.info(f"📺 Discovered {len(discovery_result.videos)} videos")

        # Step 2: Extract + validate + save
        pipeline = RecipeAutomationPipeline()
        extraction_stats = await pipeline.process_videos(discovery_result.videos)

        run_end = datetime.now(tz=timezone.utc)
        duration = (run_end - run_start).total_seconds()

        summary = {
            "status": "complete",
            "timestamp": run_start.isoformat(),
            "duration_seconds": round(duration, 1),
            "discovery": {
                "total_searched": discovery_result.total_searched,
                "videos_found": len(discovery_result.videos),
                "filtered_multi_recipe": discovery_result.filtered_multi_recipe,
                "filtered_duration": discovery_result.filtered_duration,
                "queries_used": discovery_result.queries_used,
                "errors": discovery_result.errors,
            },
            "extraction": extraction_stats.summary(),
        }

        self._log_run(summary)

        logger.info(
            f"✅ Harvest complete in {duration:.0f}s: "
            f"{extraction_stats.saved} recipes saved, "
            f"{extraction_stats.duplicates_skipped} duplicates, "
            f"{extraction_stats.failed} failed "
            f"({extraction_stats.success_rate:.0%} success rate)"
        )

        return summary

    async def _discover(self) -> DiscoveryResult:
        """Run YouTube discovery."""
        try:
            service = YouTubeDiscoveryService()
        except ValueError as e:
            logger.error(f"Discovery service init failed: {e}")
            return DiscoveryResult(errors=[str(e)])

        published_after = None
        if self.published_within_days:
            published_after = datetime.now(tz=timezone.utc) - timedelta(
                days=self.published_within_days
            )

        return await service.discover(
            max_videos=self.target_videos,
            published_after=published_after,
        )

    def _log_run(self, summary: dict):
        """Write harvest run summary to log file."""
        try:
            _ensure_log_dir()
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            log_file = HARVEST_LOG_DIR / f"harvest-{date_str}.json"

            # Append to daily log
            runs = []
            if log_file.exists():
                try:
                    runs = json.loads(log_file.read_text())
                except (json.JSONDecodeError, Exception):
                    runs = []

            runs.append(summary)
            log_file.write_text(json.dumps(runs, indent=2))
        except Exception as e:
            logger.error(f"Failed to write harvest log: {e}")


# === API Endpoint Integration ===

def get_harvest_router():
    """Create FastAPI router for harvest endpoint."""
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/v1/admin", tags=["admin-harvest"])

    @router.post("/harvest")
    async def trigger_harvest(
        target_videos: int = 50,
        admin_key: str = "",
    ):
        """Trigger a manual harvest run. Requires admin API key."""
        if admin_key != settings.ADMIN_API_KEY or not settings.ADMIN_API_KEY:
            raise HTTPException(status_code=403, detail="Invalid admin key")

        harvester = RecipeHarvester(target_videos=target_videos)
        summary = await harvester.run()
        return summary

    @router.get("/harvest/logs")
    async def get_harvest_logs(
        date: Optional[str] = None,
        admin_key: str = "",
    ):
        """Get harvest run logs for a given date (YYYY-MM-DD)."""
        if admin_key != settings.ADMIN_API_KEY or not settings.ADMIN_API_KEY:
            raise HTTPException(status_code=403, detail="Invalid admin key")

        if not date:
            date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        log_file = HARVEST_LOG_DIR / f"harvest-{date}.json"
        if not log_file.exists():
            return {"date": date, "runs": []}

        try:
            runs = json.loads(log_file.read_text())
        except Exception:
            runs = []

        return {"date": date, "runs": runs}

    return router


# === CLI Entry Point ===

async def _main():
    """CLI entry point for cron jobs."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    target = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    harvester = RecipeHarvester(target_videos=target)
    summary = await harvester.run()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
