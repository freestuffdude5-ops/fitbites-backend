"""
FitBites Premium Pricing Engine
---
Manages subscription tiers, A/B pricing experiments, and paywall logic.
Designed to integrate with Apple IAP and Stripe for web checkout.

Features:
- Multi-tier pricing (Free / Pro / Pro+)
- A/B test framework for price points
- Cohort assignment (deterministic by user_id)
- Web vs app store price differential (avoid Apple 30% tax)
- Paywall trigger rules (e.g., after 5 saves, after 3 meal plans)
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Subscription Tiers ───────────────────────────────────────────────────────

class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    PRO_PLUS = "pro_plus"


@dataclass(frozen=True)
class TierConfig:
    tier: Tier
    name: str
    price_monthly_web: float     # Stripe (2.9% fee)
    price_monthly_app: float     # Apple IAP (15% SBP fee)
    price_annual_web: float
    price_annual_app: float
    features: list[str]
    limits: dict[str, int | None]  # None = unlimited
    apple_product_id: str = ""
    stripe_price_id: str = ""


# Default pricing (can be overridden by A/B test)
DEFAULT_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        name="Free",
        price_monthly_web=0, price_monthly_app=0,
        price_annual_web=0, price_annual_app=0,
        features=[
            "Browse all recipes",
            "Save up to 10 recipes",
            "Basic nutrition info",
            "Affiliate ingredient links",
        ],
        limits={
            "saved_recipes": 10,
            "meal_plans_per_month": 1,
            "grocery_lists_per_month": 2,
            "ai_recommendations": 5,
        },
    ),
    Tier.PRO: TierConfig(
        tier=Tier.PRO,
        name="FitBites Pro",
        price_monthly_web=4.99,
        price_monthly_app=5.99,   # +$1 to offset Apple's 15%
        price_annual_web=39.99,   # ~$3.33/mo — 33% savings
        price_annual_app=49.99,   # ~$4.17/mo
        features=[
            "Unlimited saved recipes",
            "Weekly meal plans (auto-generated)",
            "Smart grocery lists",
            "Detailed macro tracking",
            "Priority new recipe access",
            "No ads",
        ],
        limits={
            "saved_recipes": None,
            "meal_plans_per_month": None,
            "grocery_lists_per_month": None,
            "ai_recommendations": 50,
        },
        apple_product_id="com.83apps.fitbites.pro.monthly",
        stripe_price_id="",  # Set after Stripe setup
    ),
    Tier.PRO_PLUS: TierConfig(
        tier=Tier.PRO_PLUS,
        name="FitBites Pro+",
        price_monthly_web=9.99,
        price_monthly_app=11.99,
        price_annual_web=79.99,   # ~$6.67/mo
        price_annual_app=99.99,   # ~$8.33/mo
        features=[
            "Everything in Pro",
            "AI personal chef (custom recipe generation)",
            "1-tap grocery ordering (Instacart integration)",
            "Advanced body composition tracking",
            "Recipe creator analytics",
            "Early access to new features",
        ],
        limits={
            "saved_recipes": None,
            "meal_plans_per_month": None,
            "grocery_lists_per_month": None,
            "ai_recommendations": None,
        },
        apple_product_id="com.83apps.fitbites.proplus.monthly",
        stripe_price_id="",
    ),
}


# ── A/B Test Framework ───────────────────────────────────────────────────────

@dataclass
class PricingExperiment:
    """An active A/B pricing experiment."""
    experiment_id: str
    name: str
    tier: Tier
    variants: list[PricingVariant]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class PricingVariant:
    """A single variant in a pricing experiment."""
    variant_id: str           # e.g., "control", "low", "high"
    price_monthly_web: float
    price_monthly_app: float
    price_annual_web: float
    price_annual_app: float
    weight: float = 0.5       # Traffic allocation (0-1)


# Pre-configured experiments
EXPERIMENTS: dict[str, PricingExperiment] = {
    "pro_price_test_v1": PricingExperiment(
        experiment_id="pro_price_test_v1",
        name="Pro Monthly Price Test: $4.99 vs $3.99 vs $6.99",
        tier=Tier.PRO,
        variants=[
            PricingVariant(
                variant_id="control",
                price_monthly_web=4.99, price_monthly_app=5.99,
                price_annual_web=39.99, price_annual_app=49.99,
                weight=0.34,
            ),
            PricingVariant(
                variant_id="low",
                price_monthly_web=3.99, price_monthly_app=4.99,
                price_annual_web=29.99, price_annual_app=39.99,
                weight=0.33,
            ),
            PricingVariant(
                variant_id="high",
                price_monthly_web=6.99, price_monthly_app=7.99,
                price_annual_web=54.99, price_annual_app=64.99,
                weight=0.33,
            ),
        ],
    ),
}


class PricingEngine:
    """Resolves pricing for a user, including A/B test assignment."""

    def __init__(self, experiments: dict[str, PricingExperiment] | None = None):
        self.tiers = dict(DEFAULT_TIERS)
        self.experiments = experiments or EXPERIMENTS

    def assign_variant(self, user_id: str, experiment_id: str) -> Optional[PricingVariant]:
        """Deterministically assign a user to a pricing variant.

        Uses hash-based assignment so the same user always sees the same price.
        """
        exp = self.experiments.get(experiment_id)
        if not exp or not exp.is_active:
            return None

        # Deterministic hash → bucket
        hash_input = f"{user_id}:{experiment_id}".encode()
        hash_val = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
        bucket = (hash_val % 10000) / 10000  # 0.0 to 0.9999

        cumulative = 0.0
        for variant in exp.variants:
            cumulative += variant.weight
            if bucket < cumulative:
                return variant

        return exp.variants[-1]  # fallback

    def get_pricing(self, user_id: str, tier: Tier, platform: str = "web") -> dict[str, Any]:
        """Get resolved pricing for a user, including any active experiments."""
        base = self.tiers[tier]

        # Check for active experiments on this tier
        active_variant = None
        active_experiment = None
        for exp_id, exp in self.experiments.items():
            if exp.tier == tier and exp.is_active:
                variant = self.assign_variant(user_id, exp_id)
                if variant:
                    active_variant = variant
                    active_experiment = exp_id
                break

        if active_variant:
            if platform == "web":
                monthly = active_variant.price_monthly_web
                annual = active_variant.price_annual_web
            else:
                monthly = active_variant.price_monthly_app
                annual = active_variant.price_annual_app
        else:
            if platform == "web":
                monthly = base.price_monthly_web
                annual = base.price_annual_web
            else:
                monthly = base.price_monthly_app
                annual = base.price_annual_app

        annual_monthly = round(annual / 12, 2)
        savings_pct = round((1 - annual_monthly / monthly) * 100) if monthly > 0 else 0

        return {
            "tier": tier.value,
            "name": base.name,
            "price_monthly": monthly,
            "price_annual": annual,
            "price_annual_per_month": annual_monthly,
            "annual_savings_pct": savings_pct,
            "features": base.features,
            "limits": base.limits,
            "platform": platform,
            "experiment": active_experiment,
            "variant": active_variant.variant_id if active_variant else "default",
            "apple_product_id": base.apple_product_id if platform != "web" else None,
        }

    def get_all_tiers(self, user_id: str, platform: str = "web") -> list[dict[str, Any]]:
        """Get pricing for all tiers (for paywall display)."""
        return [self.get_pricing(user_id, tier, platform) for tier in Tier]

    def check_limit(self, tier: Tier, feature: str, current_usage: int) -> dict[str, Any]:
        """Check if a user has hit a feature limit."""
        config = self.tiers[tier]
        limit = config.limits.get(feature)

        if limit is None:
            return {"allowed": True, "limit": None, "usage": current_usage, "remaining": None}

        remaining = max(0, limit - current_usage)
        return {
            "allowed": current_usage < limit,
            "limit": limit,
            "usage": current_usage,
            "remaining": remaining,
            "upgrade_tier": Tier.PRO.value if tier == Tier.FREE else Tier.PRO_PLUS.value,
            "message": f"You've used {current_usage}/{limit} {feature.replace('_', ' ')}. "
                       f"Upgrade to unlock unlimited." if remaining <= 2 else None,
        }


# ── Paywall Trigger Rules ────────────────────────────────────────────────────

@dataclass
class PaywallTrigger:
    """Defines when to show a paywall/upgrade prompt."""
    trigger_id: str
    event: str           # analytics event that triggers check
    threshold: int       # show paywall after this many occurrences
    feature: str         # which limit to check
    message: str         # copy for the paywall
    urgency: str = "soft"  # soft (dismissable) | hard (blocks action)


PAYWALL_TRIGGERS = [
    PaywallTrigger(
        trigger_id="save_limit",
        event="recipe_save",
        threshold=8,          # Show at 8/10 (2 remaining)
        feature="saved_recipes",
        message="You're running low on recipe saves! Upgrade to Pro for unlimited saves and weekly meal plans.",
        urgency="soft",
    ),
    PaywallTrigger(
        trigger_id="save_hard_limit",
        event="recipe_save",
        threshold=10,
        feature="saved_recipes",
        message="You've reached your save limit. Upgrade to Pro to save unlimited recipes.",
        urgency="hard",
    ),
    PaywallTrigger(
        trigger_id="meal_plan_limit",
        event="meal_plan_create",
        threshold=1,
        feature="meal_plans_per_month",
        message="Want more meal plans? Pro members get unlimited AI-generated weekly plans.",
        urgency="soft",
    ),
    PaywallTrigger(
        trigger_id="grocery_list_limit",
        event="grocery_list_generated",
        threshold=2,
        feature="grocery_lists_per_month",
        message="Upgrade to Pro for unlimited smart grocery lists with 1-tap ordering.",
        urgency="hard",
    ),
]


# ── API Route ────────────────────────────────────────────────────────────────

from fastapi import APIRouter, Query as QueryParam

pricing_router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])
_engine = PricingEngine()


@pricing_router.get("/tiers")
async def get_tiers(
    user_id: str = QueryParam("anonymous", description="User ID for A/B assignment"),
    platform: str = QueryParam("web", description="web | ios | android"),
):
    """Get all subscription tiers with resolved pricing (including A/B variants)."""
    return {
        "tiers": _engine.get_all_tiers(user_id, platform),
        "recommended": Tier.PRO.value,
        "trial_days": 7,
    }


@pricing_router.get("/tiers/{tier}")
async def get_tier(
    tier: Tier,
    user_id: str = QueryParam("anonymous"),
    platform: str = QueryParam("web"),
):
    """Get pricing for a specific tier."""
    return _engine.get_pricing(user_id, tier, platform)


@pricing_router.get("/check-limit")
async def check_feature_limit(
    tier: Tier = QueryParam(Tier.FREE),
    feature: str = QueryParam(..., description="Feature to check (e.g., saved_recipes)"),
    usage: int = QueryParam(0, description="Current usage count"),
):
    """Check if a user has hit a feature limit and whether to show paywall."""
    limit_check = _engine.check_limit(tier, feature, usage)

    # Find relevant paywall trigger
    paywall = None
    if not limit_check["allowed"] or (limit_check["remaining"] is not None and limit_check["remaining"] <= 2):
        for trigger in PAYWALL_TRIGGERS:
            if trigger.feature == feature:
                if usage >= trigger.threshold:
                    paywall = {
                        "show": True,
                        "urgency": trigger.urgency,
                        "message": trigger.message,
                        "upgrade_tier": limit_check.get("upgrade_tier", Tier.PRO.value),
                    }
                    break

    return {**limit_check, "paywall": paywall}
