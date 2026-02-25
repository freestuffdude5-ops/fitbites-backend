"""Scraper pipeline orchestrator — runs all scrapers, extracts recipes via AI, stores results."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from src.scrapers.youtube import YouTubeScraper
from src.scrapers.reddit import RedditScraper
from src.scrapers.reddit_public import RedditPublicScraper
from src.scrapers.tiktok import TikTokScraper
from src.scrapers.instagram import InstagramScraper
from src.services.recipe_extractor import RecipeExtractor
from src.services.recipe_extractor_local import extract_recipe_local
from src.services.affiliate import enrich_recipe
from src.services.viral_score import compute_viral_score, score_and_rank
from src.models import Recipe

logger = logging.getLogger(__name__)


class ScraperPipeline:
    """Orchestrates scraping across platforms, AI extraction, and storage."""

    def __init__(
        self,
        youtube_api_key: str | None = None,
        reddit_client_id: str | None = None,
        reddit_client_secret: str | None = None,
        tiktok_api_key: str | None = None,
        tiktok_api_base: str | None = None,
        instagram_api_key: str | None = None,
        instagram_api_base: str | None = None,
        anthropic_api_key: str | None = None,
        affiliate_tag: str | None = None,
        enrich_affiliates: bool = True,
    ):
        self.affiliate_tag = affiliate_tag or "fitbites-20"
        self.enrich_affiliates = enrich_affiliates
        self.scrapers = []
        if youtube_api_key:
            self.scrapers.append(YouTubeScraper(youtube_api_key))
        if reddit_client_id and reddit_client_secret:
            self.scrapers.append(RedditScraper(reddit_client_id, reddit_client_secret))
        else:
            # Fallback: use public Reddit JSON API (no keys needed)
            self.scrapers.append(RedditPublicScraper())
        if tiktok_api_key:
            self.scrapers.append(TikTokScraper(tiktok_api_key, tiktok_api_base))
        if instagram_api_key:
            self.scrapers.append(InstagramScraper(instagram_api_key, instagram_api_base))

        self.extractor = RecipeExtractor(anthropic_api_key) if anthropic_api_key else None

    async def run(self, limit_per_platform: int = 20) -> list[Recipe]:
        """Run full pipeline: scrape → extract → score → return recipes."""
        recipes = []

        for scraper in self.scrapers:
            logger.info(f"Scraping {scraper.platform}...")
            count = 0
            async for raw_data in scraper.scrape(limit=limit_per_platform):
                recipe = None
                if self.extractor:
                    recipe = await self.extractor.extract(raw_data)
                else:
                    # Fallback to local regex-based extraction (no API needed)
                    recipe = extract_recipe_local(raw_data)
                if recipe:
                    recipe.id = str(uuid.uuid4())
                    recipe.virality_score = compute_viral_score(recipe)
                    # Auto-enrich with affiliate links
                    if self.enrich_affiliates and recipe.ingredients:
                        try:
                            recipe_dict = recipe.model_dump() if hasattr(recipe, 'model_dump') else recipe.__dict__
                            # Normalize ingredients to strings for affiliate enrichment
                            raw_ings = []
                            for ing in recipe_dict.get("ingredients", []):
                                if isinstance(ing, str):
                                    raw_ings.append(ing)
                                elif isinstance(ing, dict):
                                    raw_ings.append(f"{ing.get('quantity', '')} {ing.get('name', '')}".strip())
                                elif hasattr(ing, 'name'):
                                    raw_ings.append(f"{getattr(ing, 'quantity', '')} {ing.name}".strip())
                            recipe_dict["ingredients"] = raw_ings
                            enriched = enrich_recipe(recipe_dict, tag=self.affiliate_tag)
                            recipe.affiliate_links = enriched.get("affiliate_links", [])
                        except Exception:
                            pass  # Non-critical: affiliate enrichment is done at API response time too
                    recipes.append(recipe)
                    count += 1
                    logger.info(
                        f"  Extracted: {recipe.title} "
                        f"({recipe.nutrition.calories}cal, {recipe.nutrition.protein_g}g protein)"
                        if recipe.nutrition
                        else f"  Extracted: {recipe.title}"
                    )

            logger.info(f"  {scraper.platform}: {count} recipes extracted")

            await scraper.close()

        # Sort by virality (uses health-weighted scoring from IRIS research)
        recipes = score_and_rank(recipes)
        logger.info(f"Pipeline complete: {len(recipes)} total recipes")
        return recipes
