"""Startup validation — catch misconfigurations before the app serves traffic."""
from __future__ import annotations

import logging
import sys

from config.settings import settings

logger = logging.getLogger(__name__)


def validate_settings() -> list[str]:
    """Validate configuration. Returns list of warnings (empty = all good).
    
    Raises SystemExit for critical misconfigurations in production.
    """
    warnings: list[str] = []
    is_prod = settings.DATABASE_URL and "sqlite" not in settings.DATABASE_URL

    # Critical: JWT secret must be changed in production
    if is_prod and settings.JWT_SECRET == "fitbites-dev-secret-change-in-prod":
        logger.critical("JWT_SECRET is still the default! Set a real secret for production.")
        sys.exit(1)

    # Critical: CORS should not be * in production
    if is_prod and "*" in settings.CORS_ORIGINS:
        warnings.append("CORS_ORIGINS is set to * — restrict in production")

    # Warn if no scraper keys configured
    has_scraper = any([
        settings.YOUTUBE_API_KEY,
        settings.REDDIT_CLIENT_ID,
    ])
    if not has_scraper:
        warnings.append("No scraper API keys configured — recipe scraping disabled")

    if not settings.ANTHROPIC_API_KEY:
        warnings.append("ANTHROPIC_API_KEY not set — AI recipe extraction disabled")

    # Warn if affiliate tracking has no base URL
    if not settings.API_BASE_URL:
        warnings.append("API_BASE_URL not set — tracked affiliate links will use relative URLs")

    # Stripe
    if is_prod and not settings.STRIPE_SECRET_KEY:
        warnings.append("STRIPE_SECRET_KEY not set — subscription billing disabled")

    for w in warnings:
        logger.warning("⚠️  %s", w)

    if not warnings:
        logger.info("✅ All startup checks passed")

    return warnings
