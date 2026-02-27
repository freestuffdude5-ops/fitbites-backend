"""FitBites API — FastAPI application with DB-backed storage."""
from __future__ import annotations

import json
import logging
import time

from src.logging_config import setup_logging
setup_logging()
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Recipe, Platform
from src.db.engine import engine, get_session
from src.db.tables import Base, RecipeRow
from src.db.repository import RecipeRepository
from src.services.pipeline import ScraperPipeline
from src.services.scheduler import start_scheduler, stop_scheduler
from src.services.affiliate import enrich_ingredients, enrich_recipe, get_shop_all_url, generate_click_id
from src.services.affiliate_compliance import (
    generate_compliance_metadata,
    inject_compliance_into_response,
    generate_disclosure_page_html,
    DisclosureLevel,
)
from src.services.affiliate_redirect import (
    create_tracked_links_for_recipe, store_links, lookup_link,
    record_click, get_click_stats, cleanup_expired,
)
from config.settings import settings

# ── Sentry Error Tracking ────────────────────────
if settings.SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=0.1,  # Profile 10% of transactions
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
        # Scrub sensitive data
        send_default_pii=False,
        before_send=lambda event, hint: (
            {**event, "request": {**event.get("request", {}), "cookies": None}}
            if "request" in event else event
        ),
    )


def _build_pipeline() -> ScraperPipeline:
    """Build a ScraperPipeline with all configured platform keys."""
    return ScraperPipeline(
        youtube_api_key=settings.YOUTUBE_API_KEY,
        reddit_client_id=settings.REDDIT_CLIENT_ID,
        reddit_client_secret=settings.REDDIT_CLIENT_SECRET,
        tiktok_api_key=settings.TIKTOK_API_KEY,
        tiktok_api_base=settings.TIKTOK_API_BASE,
        instagram_api_key=settings.INSTAGRAM_API_KEY,
        instagram_api_base=settings.INSTAGRAM_API_BASE,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
    )

logger = logging.getLogger(__name__)


# ── Admin auth helper (timing-safe) ──────────────────────────────────────────
import hmac as _hmac
from fastapi import Header


def _verify_admin(x_admin_key: str = Header(None)) -> None:
    """Verify admin API key (timing-safe). Used by scrape + revenue endpoints."""
    expected = settings.ADMIN_API_KEY if hasattr(settings, 'ADMIN_API_KEY') else None
    if not expected:
        raise HTTPException(503, "Admin endpoints disabled")
    if not x_admin_key or not _hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(403, "Invalid admin key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, start scheduler, optionally run initial scrape."""
    # Validate configuration before anything else
    from src.startup_checks import validate_settings
    validate_settings()

    # Import all tables so they're registered with Base.metadata
    import src.analytics.tables  # noqa: F401
    import src.db.user_tables  # noqa: F401
    import src.db.meal_plan_tables  # noqa: F401
    import src.db.review_tables  # noqa: F401
    import src.db.subscription_tables  # noqa: F401
    import src.db.social_tables  # noqa: F401
    import src.db.comment_tables  # noqa: F401
    import src.db.recently_viewed_tables  # noqa: F401
    import src.db.tracking_tables  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # Run initial scrape if configured
    if settings.ANTHROPIC_API_KEY and any([settings.YOUTUBE_API_KEY, settings.REDDIT_CLIENT_ID, settings.TIKTOK_API_KEY, settings.INSTAGRAM_API_KEY]):
        logger.info("Running initial scrape pipeline...")
        try:
            pipeline = _build_pipeline()
            recipes = await pipeline.run(limit_per_platform=settings.RECIPES_PER_PLATFORM)
            from src.db.engine import async_session
            async with async_session() as session:
                repo = RecipeRepository(session)
                for recipe in recipes:
                    await repo.upsert(recipe)
                await session.commit()
            logger.info(f"Stored {len(recipes)} recipes from initial scrape")
        except Exception:
            logger.exception("Initial scrape failed — API still starts")

    # Start background scheduler
    start_scheduler(interval_hours=settings.SCRAPE_INTERVAL_HOURS)

    yield

    logger.info("Shutting down — draining connections...")
    stop_scheduler()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="FitBites API",
    version="0.2.0",
    description="Recipe discovery API for FitBites — healthy viral recipes with affiliate links",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers — outermost layer
from src.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# Prometheus metrics
from src.middleware.metrics import MetricsMiddleware
app.add_middleware(MetricsMiddleware)

# Request ID tracing
from src.middleware.request_id import RequestIDMiddleware
app.add_middleware(RequestIDMiddleware)

# Response caching for read-heavy endpoints (recipe listings, trending)
from src.middleware.cache import ResponseCacheMiddleware
app.add_middleware(ResponseCacheMiddleware)

# Rate limiting middleware — must be added before analytics
from src.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Analytics middleware — logs request timing to DB
from src.analytics.middleware import AnalyticsMiddleware
app.add_middleware(AnalyticsMiddleware)


# ---- Auth routes ----
from src.auth import (
    SignUpRequest, LoginRequest, create_tokens, hash_password, verify_password,
    get_current_user, require_user, refresh_access_token,
)
from src.db.user_tables import UserRow, SavedRecipeRow


@app.post("/api/v1/auth/signup")
async def signup(req: SignUpRequest, session: AsyncSession = Depends(get_session)):
    """Create a new user account."""
    from sqlalchemy import select as sel
    existing = await session.execute(sel(UserRow).where(UserRow.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")
    user = UserRow(
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    tokens = create_tokens(user.id)
    return {"user": {"id": user.id, "email": user.email, "display_name": user.display_name}, **tokens}


@app.post("/api/v1/auth/login")
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    """Log in with email + password, returns JWT tokens."""
    from sqlalchemy import select as sel
    result = await session.execute(sel(UserRow).where(UserRow.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    tokens = create_tokens(user.id)
    return {"user": {"id": user.id, "email": user.email, "display_name": user.display_name}, **tokens}


class RefreshRequest(BaseModel):
    refresh_token: str

@app.post("/api/v1/auth/refresh")
async def refresh_token(
    req: RefreshRequest,
    session: AsyncSession = Depends(get_session),
):
    """Exchange a valid refresh token for new access + refresh tokens."""
    from src.auth import _verify
    payload = _verify(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid or expired refresh token")
    user_id = payload.get("sub")
    from sqlalchemy import select as sel
    result = await session.execute(sel(UserRow).where(UserRow.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "User not found")
    tokens = create_tokens(user.id)
    return {"user": {"id": user.id, "email": user.email, "display_name": user.display_name}, **tokens}


@app.get("/api/v1/me/saved")
async def list_saved(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get the current user's saved recipes."""
    from sqlalchemy import select as sel
    stmt = (
        sel(RecipeRow)
        .join(SavedRecipeRow, SavedRecipeRow.recipe_id == RecipeRow.id)
        .where(SavedRecipeRow.user_id == user.id)
        .order_by(SavedRecipeRow.saved_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    repo = RecipeRepository(session)
    recipes = [repo._row_to_recipe(r) if hasattr(repo, '_row_to_recipe') else r for r in rows]
    # Use module-level converter
    from src.db.repository import _row_to_recipe
    recipes = [_row_to_recipe(r) for r in rows]
    return {"data": recipes, "total": len(recipes)}


@app.post("/api/v1/recipes/{recipe_id}/save")
async def save_recipe(
    recipe_id: str,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Save a recipe to user's favorites."""
    from sqlalchemy import select as sel
    # Verify recipe exists
    recipe = await session.execute(sel(RecipeRow).where(RecipeRow.id == recipe_id))
    if not recipe.scalar_one_or_none():
        raise HTTPException(404, "Recipe not found")
    # Check if already saved
    existing = await session.execute(
        sel(SavedRecipeRow).where(
            SavedRecipeRow.user_id == user.id,
            SavedRecipeRow.recipe_id == recipe_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_saved"}
    saved = SavedRecipeRow(user_id=user.id, recipe_id=recipe_id)
    session.add(saved)
    await session.commit()
    return {"status": "saved"}


@app.delete("/api/v1/recipes/{recipe_id}/save")
async def unsave_recipe(
    recipe_id: str,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove a recipe from user's favorites."""
    from sqlalchemy import select as sel, delete
    result = await session.execute(
        delete(SavedRecipeRow).where(
            SavedRecipeRow.user_id == user.id,
            SavedRecipeRow.recipe_id == recipe_id,
        )
    )
    await session.commit()
    return {"status": "removed" if result.rowcount > 0 else "not_found"}


@app.get("/api/v1/trending")
async def trending_recipes(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """Get trending recipes sorted by virality score. Used by iOS feed."""
    from src.middleware.cache import get_cached, set_cached, cache_key
    key = cache_key("/api/v1/trending", f"limit={limit}")
    cached = get_cached(key)
    if cached:
        return cached
    repo = RecipeRepository(session)
    recipes = await repo.list_recipes(sort="virality", limit=limit, offset=0)
    result = {"data": recipes, "total": len(recipes)}
    set_cached(key, result, ttl=60)  # Cache trending for 60s
    return result


@app.get("/api/v1/feed")
async def personalized_feed(
    limit: int = Query(20, ge=1, le=100),
    user: "UserRow | None" = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Personalized recipe feed based on user preferences.

    If user is logged in with preferences, filters by their dietary tags
    and sorts by a combined score (virality + preference match).
    Falls back to trending if no preferences set.
    """
    from src.middleware.cache import get_cached, set_cached, cache_key
    user_id = user.id if user else "anon"
    key = cache_key(f"/api/v1/feed/{user_id}", f"limit={limit}")
    cached = get_cached(key)
    if cached:
        return cached

    repo = RecipeRepository(session)

    if user and user.preferences:
        preferred_tags = user.preferences.get("tags", [])
        max_cal = user.preferences.get("calorie_target")
        min_pro = user.preferences.get("protein_target")

        # Get more recipes than needed, then rank by preference match
        all_recipes = await repo.list_recipes(
            max_calories=max_cal, min_protein=min_pro,
            sort="virality", limit=limit * 3, offset=0,
        )

        # Score by preference match
        def preference_score(r):
            base = r.virality_score or 0
            tag_bonus = sum(5 for t in (r.tags or []) if t in preferred_tags)
            return base + tag_bonus

        all_recipes.sort(key=preference_score, reverse=True)
        recipes = all_recipes[:limit]
    else:
        recipes = await repo.list_recipes(sort="virality", limit=limit, offset=0)

    result = {"data": recipes, "total": len(recipes), "personalized": user is not None}
    set_cached(key, result, ttl=30)
    return result


@app.get("/api/v1/recipes/featured")
async def featured_recipes(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Get featured recipes — only high-quality ones with ingredients & engagement.

    This is what the app feed should show first. Filters for recipes that have:
    - At least 3 ingredients (actual recipes, not just posts)
    - Engagement (likes > 10)
    - Sorted by virality score
    """
    from src.middleware.cache import get_cached, set_cached, cache_key
    key = cache_key("/api/v1/recipes/featured", f"limit={limit}")
    cached = get_cached(key)
    if cached:
        return cached

    from sqlalchemy import select as sel, func as fn, text
    # Use JSON array length for ingredient filtering
    stmt = (
        sel(RecipeRow)
        .where(RecipeRow.likes > 10)
        .order_by(RecipeRow.virality_score.desc().nullslast())
        .limit(limit * 3)  # Over-fetch to filter client-side
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Filter for recipes with 3+ ingredients
    from src.db.repository import _row_to_recipe
    recipes = []
    for row in rows:
        if row.ingredients and len(row.ingredients) >= 3:
            recipes.append(_row_to_recipe(row))
            if len(recipes) >= limit:
                break

    response = {"data": recipes, "total": len(recipes)}
    set_cached(key, response, ttl=120)  # Cache for 2 min
    return response


@app.get("/")
async def root(session: AsyncSession = Depends(get_session)):
    repo = RecipeRepository(session)
    count = await repo.count()
    return {"app": "FitBites", "version": "0.2.0", "recipes": count}


@app.get("/api/v1/recipes")
async def list_recipes(
    tag: str | None = Query(None, description="Filter by tag (e.g. high-protein)"),
    platform: Platform | None = Query(None),
    max_calories: int | None = Query(None, ge=0),
    min_protein: float | None = Query(None, ge=0),
    sort: str = Query("virality", enum=["virality", "newest", "calories", "protein"]),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List recipes with filtering, sorting, and pagination metadata."""
    repo = RecipeRepository(session)
    recipes = await repo.list_recipes(
        tag=tag, platform=platform, max_calories=max_calories,
        min_protein=min_protein, sort=sort, limit=limit, offset=offset,
    )
    total = await repo.count()
    return {
        "data": recipes,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }


@app.get("/api/v1/recipes/search")
async def search_recipes(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Full-text search across recipe titles and descriptions with pagination."""
    repo = RecipeRepository(session)
    recipes = await repo.search(q, limit=limit, offset=offset)
    total = await repo.search_count(q)
    return {
        "data": recipes,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    }


# --- Recipe Integration & Daily Tracking (BYTE) --- must be before {recipe_id} catch-all
from src.api.tracking import router as tracking_router
app.include_router(tracking_router)

from src.api.recipe_tracking import router as recipe_tracking_router
app.include_router(recipe_tracking_router)


@app.get("/api/v1/recipes/{recipe_id}", response_model=Recipe)
async def get_recipe(recipe_id: str, session: AsyncSession = Depends(get_session)):
    """Get a single recipe by ID."""
    repo = RecipeRepository(session)
    recipe = await repo.get_by_id(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return recipe


@app.post("/api/v1/affiliate-links")
async def get_affiliate_links(ingredients: list[str]):
    """Generate multi-provider affiliate links for a list of ingredients.

    Returns links from Amazon, iHerb, Instacart, and Thrive Market,
    sorted by commission rate (highest first).
    
    Includes FTC-compliant affiliate disclosure metadata.
    """
    enriched = enrich_ingredients(ingredients)
    # Extract provider list for compliance
    providers = set()
    for item in enriched:
        for link in item.get("all_links", []):
            providers.add(link.get("provider", ""))
    providers.discard("")
    
    # Wrap in dict for compliance injection
    response = {"ingredients": enriched}
    return inject_compliance_into_response(response, list(providers))


@app.post("/api/v1/affiliate-links/shop-all")
async def shop_all_ingredients(ingredients: list[str]):
    """Generate a 'Shop All Ingredients' link for one-click grocery ordering.

    This is the highest-value monetization touchpoint — routes to Instacart
    with all ingredients pre-loaded for instant cart building.
    """
    if not ingredients:
        raise HTTPException(400, "At least one ingredient required")
    return get_shop_all_url(ingredients)


@app.post("/api/v1/affiliate-clicks")
async def track_affiliate_click(
    recipe_id: str,
    ingredient: str,
    provider: str,
    user: "UserRow | None" = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Track an affiliate link click for analytics and commission attribution.

    Returns a click_id for deduplication on the client side.
    """
    user_id = user.id if user else None
    click_id = generate_click_id(user_id, recipe_id, ingredient, provider)

    # Store click in DB (fire-and-forget pattern for speed)
    try:
        from sqlalchemy import text
        await session.execute(
            text("""
                INSERT INTO affiliate_clicks (id, user_id, recipe_id, platform, clicked_at)
                VALUES (gen_random_uuid(), :user_id, :recipe_id::uuid, :platform, NOW())
            """),
            {"user_id": user_id, "recipe_id": recipe_id, "platform": provider},
        )
        await session.commit()
    except Exception:
        logger.warning(f"Failed to store affiliate click: {click_id}", exc_info=True)
        # Don't fail the request — click tracking is best-effort

    return {"click_id": click_id, "tracked": True}


# Simple in-memory rate limiter for scrape endpoint
_last_scrape_time: float = 0.0
_SCRAPE_COOLDOWN_SECONDS: int = 300  # 5 minutes between scrapes


@app.post("/api/v1/scrape")
async def trigger_scrape(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(_verify_admin),
):
    """Manually trigger a scrape run (rate limited, admin-only)."""
    global _last_scrape_time
    now = time.time()
    if now - _last_scrape_time < _SCRAPE_COOLDOWN_SECONDS:
        remaining = int(_SCRAPE_COOLDOWN_SECONDS - (now - _last_scrape_time))
        raise HTTPException(429, f"Rate limited. Try again in {remaining}s")
    _last_scrape_time = now
    pipeline = _build_pipeline()
    recipes = await pipeline.run(limit_per_platform=settings.RECIPES_PER_PLATFORM)
    repo = RecipeRepository(session)
    stored = 0
    for recipe in recipes:
        await repo.upsert(recipe)
        stored += 1
    await session.commit()
    return {"scraped": len(recipes), "stored": stored}


# --- Analytics routes ---
from src.analytics.routes import router as analytics_router
app.include_router(analytics_router)

# --- Revenue analytics (FINN) ---
from src.analytics.revenue import router as revenue_router
app.include_router(revenue_router)

# --- Pricing & subscription tiers (FINN) ---
from src.services.pricing import pricing_router
app.include_router(pricing_router)

# --- Subscription management: Stripe + Apple IAP (FINN) ---
from src.services.subscriptions import router as subscriptions_router
app.include_router(subscriptions_router)

# --- Google Play Billing (FINN) ---
from src.services.google_play import router as google_play_router
app.include_router(google_play_router)

# --- Data Privacy: CCPA/GDPR deletion, export, consent (FINN) ---
from src.services.data_privacy import router as privacy_router
app.include_router(privacy_router)

# --- Data Retention: Automated lifecycle management (FINN) ---
from src.services.data_retention import router as retention_router
app.include_router(retention_router)

# --- Revenue Alerts: Financial health monitoring (FINN) ---
from src.services.revenue_alerts import router as alerts_router
app.include_router(alerts_router)

# --- Affiliate Performance: Revenue optimization (FINN) ---
from src.services.affiliate_performance import router as affiliate_perf_router
app.include_router(affiliate_perf_router)

# --- User routes (favorites, grocery lists) ---
from src.api.users import router as users_router
app.include_router(users_router)

# --- Recommendations & Meal Plans ---
from src.api.recommendations import router as recommendations_router
app.include_router(recommendations_router)

# --- Reviews, Cooking History, Search Suggestions ---
from src.api.reviews import router as reviews_router
app.include_router(reviews_router)

# --- Social: follows, activity feed, shares ---
from src.api.social import router as social_router
app.include_router(social_router)

# --- Advanced search & discovery (must be before {recipe_id} catch-all) ---
from src.api.search import router as search_router
app.include_router(search_router)

from src.api.comments import router as comments_router
app.include_router(comments_router)

from src.api.recently_viewed import router as recently_viewed_router
app.include_router(recently_viewed_router)

from src.api.avatar import router as avatar_router
app.include_router(avatar_router)

from src.api.affiliate_webhooks import router as affiliate_webhooks_router
from src.api.admin import router as admin_router
from src.api.affiliate_admin import router as affiliate_admin_router
from src.api.admin_curate import router as admin_curate_router
from src.api.youtube_extract import router as youtube_extract_router
app.include_router(affiliate_webhooks_router)
app.include_router(admin_router)
app.include_router(affiliate_admin_router)
app.include_router(admin_curate_router)
app.include_router(youtube_extract_router)

from src.api.tiktok_extract import router as tiktok_extract_router
app.include_router(tiktok_extract_router)

from src.api.instagram_extract import router as instagram_extract_router
app.include_router(instagram_extract_router)

from src.tasks.recipe_harvester import get_harvest_router
app.include_router(get_harvest_router())

from src.api.collections import router as collections_router
app.include_router(collections_router)

from src.api.password_reset import router as password_reset_router
app.include_router(password_reset_router)

from src.api.onboarding import router as onboarding_router
app.include_router(onboarding_router)

from src.api.reports import router as reports_router
app.include_router(reports_router)

from src.api.shopping_list import router as shopping_list_router
app.include_router(shopping_list_router)

from src.api.sharing import router as sharing_router
app.include_router(sharing_router)

# --- Food Search & Quick-Log (ALEX) ---
from src.api.food import router as food_router
app.include_router(food_router)

from src.api.barcode import router as barcode_router
app.include_router(barcode_router)

# --- Recipe Orchestrator / Scheduler (BYTE) ---
from src.api.recipe_scheduler import router as recipe_scheduler_router
app.include_router(recipe_scheduler_router)

# ── Affiliate Redirect & Tracking ────────────────────────────────────────────

@app.post("/api/v1/affiliate-links/tracked")
async def get_tracked_affiliate_links(
    recipe_id: str,
    ingredients: list[str],
):
    """Generate tracked affiliate links that route through our redirect service.

    Instead of raw provider URLs, returns /go/{link_id} URLs that:
    - Track clicks server-side (reliable attribution)
    - Enable A/B testing of providers
    - Support dynamic link rotation
    - Work as universal deep links (web + iOS + Android)
    """
    enriched = enrich_ingredients(ingredients)

    base_url = settings.API_BASE_URL if hasattr(settings, "API_BASE_URL") else ""
    tracked = create_tracked_links_for_recipe(recipe_id, enriched, base_url=base_url)
    store_links(tracked)

    # Replace raw URLs with tracked redirect URLs in the response
    for ingredient_data in enriched:
        normalized = ingredient_data.get("normalized", "")
        for link_info in ingredient_data.get("all_links", []):
            from src.services.affiliate_redirect import _generate_link_id
            lid = _generate_link_id(recipe_id, normalized, link_info["provider"])
            link_info["tracked_url"] = f"{base_url}/go/{lid}"

        if ingredient_data.get("primary_link"):
            pl = ingredient_data["primary_link"]
            lid = _generate_link_id(recipe_id, normalized, pl["provider"])
            pl["tracked_url"] = f"{base_url}/go/{lid}"

    # Extract provider list for FTC compliance
    providers = set()
    for item in enriched:
        for link in item.get("all_links", []):
            providers.add(link.get("provider", ""))
    providers.discard("")
    
    # Wrap in dict for compliance injection
    response = {"ingredients": enriched, "recipe_id": recipe_id}
    return inject_compliance_into_response(response, list(providers))


from fastapi.responses import RedirectResponse


@app.get("/go/{link_id}")
async def redirect_affiliate(
    link_id: str,
    uid: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Redirect to affiliate provider URL while tracking the click.

    This is the core monetization endpoint — every affiliate click flows through here.
    Fast 302 redirect with async click logging.
    """
    link = lookup_link(link_id)
    if not link:
        raise HTTPException(404, "Link expired or not found")

    # Record click (non-blocking for speed)
    record_click(link, user_id=uid)

    # Also persist to DB for durable analytics
    try:
        from sqlalchemy import text as sql_text
        await session.execute(
            sql_text("""
                INSERT INTO analytics_events (id, event, user_id, properties, timestamp)
                VALUES (:id, 'affiliate_click', :uid, :props, datetime('now'))
            """),
            {
                "id": link_id + "_" + str(int(time.time())),
                "uid": uid,
                "props": json.dumps({
                    "provider": link.provider,
                    "ingredient": link.ingredient,
                    "recipe_id": link.recipe_id,
                    "commission_pct": link.commission_pct,
                }),
            },
        )
        await session.commit()
    except Exception:
        logger.debug("Click DB write failed (non-critical)", exc_info=True)

    return RedirectResponse(url=link.destination_url, status_code=302)


@app.get("/api/v1/admin/affiliate-revenue")
async def affiliate_revenue_dashboard(
    hours: int = Query(24, ge=1, le=720),
    _auth: None = Depends(_verify_admin),
):
    """Real-time affiliate revenue dashboard.

    Shows click stats, revenue estimates, and provider breakdown.
    """
    stats = get_click_stats(since_hours=hours)
    return {
        "window_hours": hours,
        **stats.to_dict(),
    }


# ── Recipe Cost Estimation ────────────────────────────────────────────────────
from src.services.recipe_cost import estimate_recipe_cost, estimate_meal_plan_cost


class CostEstimateRequest(BaseModel):
    ingredients: list[str]
    servings: int = 4


class MealPlanCostRequest(BaseModel):
    recipes: list[dict]


@app.post("/api/v1/recipes/cost-estimate")
async def recipe_cost_estimate(req: CostEstimateRequest):
    """Estimate the cost of a recipe from its ingredients.

    Returns per-ingredient costs, total, per-serving, and budget-friendly flag.
    Premium feature — shows users exactly what they'll spend.
    """
    cost = estimate_recipe_cost(req.ingredients, req.servings)
    return cost.to_dict()


@app.get("/api/v1/recipes/{recipe_id}/cost")
async def recipe_cost_by_id(
    recipe_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get cost estimate for a stored recipe by ID."""
    repo = RecipeRepository(session)
    recipe = await repo.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    ingredients = recipe.get("ingredients", [])
    servings = recipe.get("servings", 4)
    cost = estimate_recipe_cost(ingredients, servings)
    return {
        "recipe_id": recipe_id,
        "title": recipe.get("title", ""),
        **cost.to_dict(),
    }


@app.post("/api/v1/meal-plan/cost")
async def meal_plan_cost(req: MealPlanCostRequest):
    """Estimate total cost for a weekly meal plan.

    Accepts a list of recipes and returns aggregate cost with savings tips.
    """
    return estimate_meal_plan_cost(req.recipes)


# --- Static files (web frontend) ---
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
if os.path.isdir(_static_dir):
    @app.get("/app")
    async def serve_app():
        return FileResponse(os.path.join(_static_dir, "index.html"))


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    """Deep health check — validates DB connectivity."""
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"
    status = "ok" if db_status == "connected" else "degraded"
    return {"status": status, "db": db_status, "version": "0.2.0"}


@app.get("/ready")
async def readiness(session: AsyncSession = Depends(get_session)):
    """Readiness probe for orchestrators (K8s, Railway).
    
    Returns 503 if not ready to serve traffic.
    """
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "database unavailable"})
    return {"ready": True}


@app.get("/legal/affiliate-disclosure")
async def affiliate_disclosure():
    """FTC-compliant affiliate disclosure page.
    
    Required by FTC 16 CFR Part 255 for all affiliate link monetization.
    """
    from fastapi.responses import HTMLResponse
    html = generate_disclosure_page_html()
    return HTMLResponse(content=html, status_code=200)


# --- Structured Error Responses ---

from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: FastAPIRequest, exc: RequestValidationError):
    """Return clean, structured validation errors instead of raw Pydantic output."""
    errors = []
    for err in exc.errors():
        field = " → ".join(str(loc) for loc in err["loc"]) if err.get("loc") else "unknown"
        errors.append({"field": field, "message": err["msg"]})
    return JSONResponse(status_code=422, content={
        "error": "validation_error",
        "message": "Invalid request data",
        "details": errors,
    })


@app.exception_handler(HTTPException)
async def http_error_handler(request: FastAPIRequest, exc: HTTPException):
    """Consistent error envelope for all HTTP errors."""
    return JSONResponse(status_code=exc.status_code, content={
        "error": exc.detail if isinstance(exc.detail, str) else "error",
        "message": exc.detail,
    })


@app.exception_handler(Exception)
async def unhandled_error_handler(request: FastAPIRequest, exc: Exception):
    """Catch-all for unhandled exceptions — never leak stack traces."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "internal_error",
        "message": "Something went wrong. Please try again.",
    })
