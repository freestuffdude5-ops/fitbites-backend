"""Scheduled scraping service using APScheduler."""
from __future__ import annotations

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.services.pipeline import ScraperPipeline
from src.db.engine import async_session
from src.db.repository import RecipeRepository
from config.settings import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_scrape():
    """Run the full scrape pipeline and store results."""
    logger.info("Scheduled scrape starting...")
    try:
        pipeline = ScraperPipeline(
            youtube_api_key=settings.YOUTUBE_API_KEY,
            reddit_client_id=settings.REDDIT_CLIENT_ID,
            reddit_client_secret=settings.REDDIT_CLIENT_SECRET,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            tiktok_api_key=getattr(settings, "TIKTOK_API_KEY", None),
            instagram_api_key=getattr(settings, "INSTAGRAM_API_KEY", None),
        )
        recipes = await pipeline.run(limit_per_platform=settings.RECIPES_PER_PLATFORM)

        async with async_session() as session:
            repo = RecipeRepository(session)
            stored = 0
            for recipe in recipes:
                await repo.upsert(recipe)
                stored += 1
            await session.commit()

        logger.info(f"Scheduled scrape complete: {len(recipes)} scraped, {stored} stored")
    except Exception:
        logger.exception("Scheduled scrape failed")


def start_scheduler(interval_hours: int = 6):
    """Start the background scheduler for periodic scraping."""
    scheduler.add_job(
        scheduled_scrape,
        trigger=IntervalTrigger(hours=interval_hours),
        id="periodic_scrape",
        name="Periodic recipe scrape",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — scraping every {interval_hours}h")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
