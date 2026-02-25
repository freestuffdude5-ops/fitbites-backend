"""
FitBites Affiliate Performance Tracker
---
Real-time tracking of affiliate link performance by partner, recipe, and ingredient.
Powers the admin dashboard and optimizes affiliate link placement.

Endpoints:
- GET /api/v1/admin/affiliate/performance           — Overall performance summary
- GET /api/v1/admin/affiliate/performance/top-recipes — Top revenue-generating recipes
- GET /api/v1/admin/affiliate/performance/partners    — Per-partner breakdown
- GET /api/v1/admin/affiliate/performance/optimize    — Optimization recommendations
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/affiliate/performance",
    tags=["admin", "affiliate"],
)

# ── Commission Rate Map ───────────────────────────────────────────────────────
# Maps partner slugs to their commission structures for revenue estimation

PARTNER_COMMISSIONS = {
    "amazon": {
        "type": "cps",
        "rates": {
            "grocery": 0.01,
            "kitchen": 0.03,
            "supplements": 0.045,
            "default": 0.02,
        },
        "cookie_days": 1,
        "avg_order_value": 35.0,
    },
    "iherb": {
        "type": "cps",
        "rates": {"default": 0.05},
        "cookie_days": 7,
        "avg_order_value": 40.0,
    },
    "thrive_market": {
        "type": "cpa",
        "rates": {"monthly_signup": 5.0, "annual_signup": 30.0, "default": 10.0},
        "cookie_days": 14,
        "avg_order_value": None,
    },
    "instacart": {
        "type": "cpa",
        "rates": {"new_customer": 5.0, "default": 5.0},
        "cookie_days": 7,
        "avg_order_value": None,
    },
    "hellofresh": {
        "type": "cpa",
        "rates": {"new_customer": 10.0, "default": 10.0},
        "cookie_days": 7,
        "avg_order_value": None,
    },
    "factor": {
        "type": "cpa",
        "rates": {"new_customer": 25.0, "default": 25.0},
        "cookie_days": 30,
        "avg_order_value": None,
    },
}


def estimate_commission(partner: str, category: str = "default", order_value: Optional[float] = None) -> float:
    """Estimate commission for a single conversion."""
    config = PARTNER_COMMISSIONS.get(partner, PARTNER_COMMISSIONS.get("amazon"))
    if not config:
        return 0.0

    if config["type"] == "cps":
        rate = config["rates"].get(category, config["rates"]["default"])
        value = order_value or config.get("avg_order_value", 30.0)
        return value * rate
    else:  # CPA
        return config["rates"].get(category, config["rates"]["default"])


def get_partner_info(partner: str) -> dict:
    """Get partner commission info for display."""
    config = PARTNER_COMMISSIONS.get(partner)
    if not config:
        return {"partner": partner, "type": "unknown"}
    return {
        "partner": partner,
        "type": config["type"],
        "rates": config["rates"],
        "cookie_days": config["cookie_days"],
        "avg_order_value": config.get("avg_order_value"),
    }


# ── Optimization Engine ──────────────────────────────────────────────────────

def generate_recommendations(
    partner_stats: dict,
    recipe_stats: list,
) -> list[dict]:
    """Generate actionable affiliate optimization recommendations."""
    recs = []

    # Check if high-value partners are underrepresented
    cpa_partners = {"thrive_market", "factor", "hellofresh", "instacart"}
    active_partners = set(partner_stats.keys())
    missing_high_value = cpa_partners - active_partners

    if missing_high_value:
        recs.append({
            "priority": "high",
            "type": "partner_gap",
            "title": "Add high-value CPA partners",
            "description": f"Missing links for: {', '.join(missing_high_value)}. "
                          f"These pay $5-25 per conversion vs $0.30-1.50 for Amazon.",
            "estimated_impact": "$500-2000/mo at 50K MAU",
        })

    # Check for Amazon-heavy concentration
    total_clicks = sum(s.get("clicks", 0) for s in partner_stats.values())
    if total_clicks > 0:
        amazon_clicks = partner_stats.get("amazon", {}).get("clicks", 0)
        amazon_share = amazon_clicks / total_clicks if total_clicks else 0
        if amazon_share > 0.80:
            recs.append({
                "priority": "medium",
                "type": "diversification",
                "title": "Diversify affiliate partners",
                "description": f"Amazon accounts for {amazon_share:.0%} of clicks. "
                              f"Diversifying to iHerb (5% CPS) and Thrive ($10-30 CPA) "
                              f"could 3-5x affiliate revenue.",
                "estimated_impact": "3-5x revenue per click",
            })

    # Check for recipes with high views but low affiliate CTR
    for recipe in recipe_stats[:10]:
        views = recipe.get("views", 0)
        clicks = recipe.get("affiliate_clicks", 0)
        if views > 100 and clicks / max(views, 1) < 0.05:
            recs.append({
                "priority": "medium",
                "type": "ctr_optimization",
                "title": f"Optimize affiliate placement: {recipe.get('title', 'Unknown')[:50]}",
                "description": f"{views} views but only {clicks} affiliate clicks ({clicks/max(views,1):.1%} CTR). "
                              f"Consider more prominent ingredient links or 'Shop Ingredients' CTA.",
                "estimated_impact": f"+{int(views * 0.10 - clicks)} clicks/period",
            })
            if len(recs) >= 8:  # Cap recommendations
                break

    if not recs:
        recs.append({
            "priority": "info",
            "type": "status",
            "title": "Affiliate program performing well",
            "description": "No immediate optimization opportunities detected.",
            "estimated_impact": "N/A",
        })

    return recs


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("")
async def performance_summary(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Overall affiliate performance summary."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    # Try to get data from affiliate_clicks table
    total_clicks = 0
    total_conversions = 0
    total_estimated_revenue = 0.0
    partner_breakdown = {}

    try:
        result = await session.execute(
            text("""
                SELECT partner, COUNT(*) as clicks,
                       SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conversions
                FROM affiliate_clicks
                WHERE clicked_at >= :start
                GROUP BY partner
            """),
            {"start": window_start.isoformat()},
        )
        for row in result.fetchall():
            partner, clicks, conversions = row[0], row[1], row[2] or 0
            est_rev = conversions * estimate_commission(partner)
            partner_breakdown[partner] = {
                "clicks": clicks,
                "conversions": conversions,
                "conversion_rate": conversions / max(clicks, 1),
                "estimated_revenue": round(est_rev, 2),
            }
            total_clicks += clicks
            total_conversions += conversions
            total_estimated_revenue += est_rev
    except Exception as e:
        logger.debug(f"Affiliate clicks table not available: {e}")

    return {
        "period": {"days": days, "start": window_start.isoformat(), "end": now.isoformat()},
        "totals": {
            "clicks": total_clicks,
            "conversions": total_conversions,
            "conversion_rate": total_conversions / max(total_clicks, 1),
            "estimated_revenue": round(total_estimated_revenue, 2),
            "arpu_per_click": round(total_estimated_revenue / max(total_clicks, 1), 4),
        },
        "partners": partner_breakdown,
        "partner_count": len(partner_breakdown),
    }


@router.get("/top-recipes")
async def top_recipes(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Top revenue-generating recipes by affiliate clicks."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    recipes = []

    try:
        result = await session.execute(
            text("""
                SELECT ac.recipe_id, r.title, COUNT(*) as clicks,
                       SUM(CASE WHEN ac.converted = 1 THEN 1 ELSE 0 END) as conversions,
                       ac.partner
                FROM affiliate_clicks ac
                LEFT JOIN recipes r ON ac.recipe_id = r.id
                WHERE ac.clicked_at >= :start
                GROUP BY ac.recipe_id, r.title, ac.partner
                ORDER BY conversions DESC, clicks DESC
                LIMIT :limit
            """),
            {"start": window_start.isoformat(), "limit": limit},
        )
        for row in result.fetchall():
            recipe_id, title, clicks, conversions, partner = row
            est_rev = (conversions or 0) * estimate_commission(partner or "amazon")
            recipes.append({
                "recipe_id": recipe_id,
                "title": title or "Unknown",
                "clicks": clicks,
                "conversions": conversions or 0,
                "partner": partner,
                "estimated_revenue": round(est_rev, 2),
                "ctr": clicks / max(clicks, 1),  # Need views for real CTR
            })
    except Exception as e:
        logger.debug(f"Could not query top recipes: {e}")

    return {
        "period_days": days,
        "recipes": recipes,
        "total": len(recipes),
    }


@router.get("/partners")
async def partner_details(admin=Depends(require_admin)):
    """Detailed partner commission info and setup status."""
    partners = []
    for slug, config in PARTNER_COMMISSIONS.items():
        partners.append({
            "partner": slug,
            "commission_type": config["type"],
            "rates": config["rates"],
            "cookie_days": config["cookie_days"],
            "avg_order_value": config.get("avg_order_value"),
            "estimated_per_conversion": estimate_commission(slug),
        })
    # Sort by estimated revenue per conversion (highest first)
    partners.sort(key=lambda p: p["estimated_per_conversion"], reverse=True)
    return {"partners": partners}


@router.get("/optimize")
async def optimization_recommendations(
    days: int = Query(30, ge=1, le=365),
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Get actionable optimization recommendations."""
    # Gather stats for recommendation engine
    partner_stats = {}
    recipe_stats = []

    try:
        result = await session.execute(
            text("""
                SELECT partner, COUNT(*) as clicks,
                       SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) as conversions
                FROM affiliate_clicks
                WHERE clicked_at >= :start
                GROUP BY partner
            """),
            {"start": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()},
        )
        for row in result.fetchall():
            partner_stats[row[0]] = {"clicks": row[1], "conversions": row[2] or 0}
    except Exception:
        pass

    recs = generate_recommendations(partner_stats, recipe_stats)
    return {
        "recommendations": recs,
        "total": len(recs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
