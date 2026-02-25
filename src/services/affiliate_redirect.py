"""
Affiliate Link Redirect & Tracking Service for FitBites.

Instead of exposing raw affiliate URLs to clients, we route all clicks through
our server. This gives us:
1. Server-side click tracking (reliable, not dependent on client JS)
2. A/B testing of providers per ingredient category
3. Dynamic link rotation (if a provider goes down or changes terms)
4. Revenue attribution and reporting
5. Universal deep linking (same URL works web + iOS + Android)

Flow:
  Client taps "Buy on Instacart" →
  GET /go/{link_id} →
  Server logs click + redirects to provider URL (302)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# HMAC key for signing link IDs (prevents enumeration/tampering)
_SIGNING_KEY = b"fitbites-affiliate-2026"  # TODO: move to env var


@dataclass(frozen=True)
class TrackedLink:
    """A tracked affiliate link with a short redirect ID."""
    link_id: str          # short ID for redirect URL (e.g., "a3f8b2c1")
    redirect_url: str     # our redirect endpoint: /go/{link_id}
    destination_url: str  # actual affiliate URL
    provider: str
    ingredient: str
    recipe_id: str
    commission_pct: float


def _generate_link_id(recipe_id: str, ingredient: str, provider: str) -> str:
    """Generate a short, deterministic, tamper-resistant link ID."""
    payload = f"{recipe_id}:{ingredient}:{provider}".encode()
    sig = hmac.new(_SIGNING_KEY, payload, hashlib.sha256).hexdigest()
    return sig[:12]


def create_tracked_link(
    recipe_id: str,
    ingredient: str,
    provider: str,
    destination_url: str,
    commission_pct: float,
    base_url: str = "",  # e.g., "https://api.fitbites.app"
) -> TrackedLink:
    """Create a tracked affiliate link that routes through our redirect service."""
    link_id = _generate_link_id(recipe_id, ingredient, provider)
    redirect_url = f"{base_url}/go/{link_id}"

    return TrackedLink(
        link_id=link_id,
        redirect_url=redirect_url,
        destination_url=destination_url,
        provider=provider,
        ingredient=ingredient,
        recipe_id=recipe_id,
        commission_pct=commission_pct,
    )


def create_tracked_links_for_recipe(
    recipe_id: str,
    enriched_ingredients: list[dict],
    base_url: str = "",
) -> dict[str, TrackedLink]:
    """Create tracked links for all affiliate links in a recipe.

    Returns a dict mapping link_id → TrackedLink for the redirect lookup table.
    """
    links: dict[str, TrackedLink] = {}

    for ingredient_data in enriched_ingredients:
        ingredient_name = ingredient_data.get("normalized", ingredient_data.get("ingredient", ""))
        for link_info in ingredient_data.get("all_links", []):
            tracked = create_tracked_link(
                recipe_id=recipe_id,
                ingredient=ingredient_name,
                provider=link_info["provider"],
                destination_url=link_info["url"],
                commission_pct=link_info.get("commission_pct", 0),
                base_url=base_url,
            )
            links[tracked.link_id] = tracked

    return links


# ── In-Memory Link Store ────────────────────────────────────────────────────
# For MVP: in-memory cache with TTL. Production: Redis or DB-backed.

_link_cache: dict[str, tuple[TrackedLink, float]] = {}
_CACHE_TTL = 86400  # 24 hours


def store_link(link: TrackedLink) -> None:
    """Store a tracked link for later redirect lookup."""
    _link_cache[link.link_id] = (link, time.time())


def store_links(links: dict[str, TrackedLink]) -> None:
    """Store multiple tracked links."""
    now = time.time()
    for link_id, link in links.items():
        _link_cache[link_id] = (link, now)


def lookup_link(link_id: str) -> Optional[TrackedLink]:
    """Look up a tracked link by ID. Returns None if expired or not found."""
    entry = _link_cache.get(link_id)
    if not entry:
        return None
    link, stored_at = entry
    if time.time() - stored_at > _CACHE_TTL:
        del _link_cache[link_id]
        return None
    return link


def cleanup_expired() -> int:
    """Remove expired links from cache. Returns count removed."""
    now = time.time()
    expired = [k for k, (_, ts) in _link_cache.items() if now - ts > _CACHE_TTL]
    for k in expired:
        del _link_cache[k]
    return len(expired)


# ── Click Analytics Aggregation ──────────────────────────────────────────────

@dataclass
class ClickStats:
    total_clicks: int = 0
    unique_recipes: int = 0
    by_provider: dict[str, int] = None
    by_ingredient: dict[str, int] = None
    estimated_revenue: float = 0.0

    def __post_init__(self):
        if self.by_provider is None:
            self.by_provider = {}
        if self.by_ingredient is None:
            self.by_ingredient = {}

    def to_dict(self) -> dict:
        return {
            "total_clicks": self.total_clicks,
            "unique_recipes": self.unique_recipes,
            "by_provider": self.by_provider,
            "by_ingredient": dict(sorted(self.by_ingredient.items(), key=lambda x: -x[1])[:20]),
            "estimated_revenue": round(self.estimated_revenue, 2),
        }


# In-memory click log for real-time stats (production: DB/analytics service)
_click_log: list[dict] = []


def record_click(link: TrackedLink, user_id: str | None = None, user_agent: str | None = None) -> None:
    """Record a click event for analytics."""
    _click_log.append({
        "link_id": link.link_id,
        "provider": link.provider,
        "ingredient": link.ingredient,
        "recipe_id": link.recipe_id,
        "commission_pct": link.commission_pct,
        "user_id": user_id,
        "timestamp": time.time(),
    })


def get_click_stats(since_hours: int = 24) -> ClickStats:
    """Aggregate click stats for the given time window."""
    cutoff = time.time() - (since_hours * 3600)
    recent = [c for c in _click_log if c["timestamp"] >= cutoff]

    stats = ClickStats()
    stats.total_clicks = len(recent)
    recipes = set()
    avg_order_value = 45.0  # estimated average grocery order

    for click in recent:
        provider = click["provider"]
        ingredient = click["ingredient"]
        commission = click["commission_pct"]

        stats.by_provider[provider] = stats.by_provider.get(provider, 0) + 1
        stats.by_ingredient[ingredient] = stats.by_ingredient.get(ingredient, 0) + 1
        recipes.add(click["recipe_id"])

        # Estimate revenue: commission_pct * avg_order_value * conversion_rate
        # Conservative: 3% of clicks convert to purchase
        stats.estimated_revenue += commission * avg_order_value * 0.03

    stats.unique_recipes = len(recipes)
    return stats
