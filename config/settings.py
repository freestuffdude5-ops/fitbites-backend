"""App settings — loaded from environment."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # API
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))

    # YouTube
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

    # Reddit
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")

    # Anthropic (for AI recipe extraction)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    # Database (future)
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///fitbites.db")

    # TikTok (3rd-party API)
    TIKTOK_API_KEY = os.getenv("TIKTOK_API_KEY")
    TIKTOK_API_BASE = os.getenv("TIKTOK_API_BASE")

    # Instagram (3rd-party API)
    INSTAGRAM_API_KEY = os.getenv("INSTAGRAM_API_KEY")
    INSTAGRAM_API_BASE = os.getenv("INSTAGRAM_API_BASE")

    # Auth
    JWT_SECRET = os.getenv("JWT_SECRET", "fitbites-dev-secret-change-in-prod")

    # API base URL (for affiliate redirect links)
    API_BASE_URL = os.getenv("API_BASE_URL", "")

    # Stripe
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # Apple IAP
    APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET", "")

    # Affiliate link signing (for tamper-proof redirect links)
    AFFILIATE_SIGNING_KEY = os.getenv(
        "AFFILIATE_SIGNING_KEY",
        "fitbites-dev-affiliate-key-change-in-prod"
    )

    # Affiliate webhook secrets (for conversion tracking)
    AFFILIATE_WEBHOOK_SECRET = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")
    AMAZON_WEBHOOK_SECRET = os.getenv("AMAZON_WEBHOOK_SECRET", "")
    IMPACT_WEBHOOK_SECRET = os.getenv("IMPACT_WEBHOOK_SECRET", "")

    # Admin API key (for protected admin endpoints like database seeding)
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

    # CORS origins (comma-separated, or * for dev)
    CORS_ORIGINS = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")
    ]

    # Scraper schedule
    SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    RECIPES_PER_PLATFORM = int(os.getenv("RECIPES_PER_PLATFORM", "20"))

    # Observability
    SENTRY_DSN = os.getenv("SENTRY_DSN", "")
    SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "development")
    SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    # Logging
    LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # "text" or "json"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
