"""
FitBites Revenue Analytics Engine
---
Real-time unit economics, LTV projections, and revenue health monitoring.
Integrates with the existing analytics events table.

Endpoints:
  GET /api/v1/admin/revenue           — Revenue summary (ARPU, LTV, by partner)
  GET /api/v1/admin/revenue/daily     — Daily revenue time series
  GET /api/v1/admin/revenue/health    — Financial health score & alerts
  GET /api/v1/admin/revenue/partners  — Per-partner breakdown with commission tracking
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.analytics.tables import AnalyticsEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin/revenue", tags=["revenue"])


# ── Commission Rate Reference ────────────────────────────────────────────────

COMMISSION_RATES = {
    "amazon": {"grocery": 0.01, "kitchen": 0.03, "supplements": 0.045, "default": 0.02},
    "iherb": {"default": 0.05},
    "instacart": {"default": 0.00, "cpa": 5.0},  # CPA model, not CPS
    "thrive": {"default": 0.00, "cpa_monthly": 5.0, "cpa_annual": 30.0},
    "hellofresh": {"default": 0.00, "cpa": 10.0},
    "factor": {"default": 0.00, "cpa": 25.0},
}

# Average order values by partner (industry benchmarks)
AVG_ORDER_VALUES = {
    "amazon": 35.0,
    "iherb": 42.0,
    "instacart": 65.0,
    "thrive": 0.0,     # CPA only
    "hellofresh": 0.0,  # CPA only
    "factor": 0.0,      # CPA only
}

# Targets for health scoring
TARGETS = {
    "arpu_monthly": 0.072,       # Base scenario ARPU
    "affiliate_ctr": 0.15,       # 15% of MAU click affiliate
    "click_to_convert": 0.03,    # 3% of clicks convert
    "d7_retention": 0.25,        # 25% 7-day retention
    "premium_conversion": 0.05,  # 5% premium (future)
}


# ── Response Models ──────────────────────────────────────────────────────────

class RevenueMetric(BaseModel):
    value: float
    label: str
    trend: float | None = None  # % change vs prior period
    status: str = "neutral"     # green | yellow | red | neutral


class RevenueSummary(BaseModel):
    period_days: int
    total_revenue_est: float
    arpu: RevenueMetric
    ltv_30d: RevenueMetric
    ltv_12m: RevenueMetric
    affiliate_ctr: RevenueMetric
    conversion_rate: RevenueMetric
    unique_users: int
    total_clicks: int
    total_conversions: int
    revenue_by_partner: dict[str, float]
    top_recipes_by_revenue: list[dict[str, Any]]


class DailyRevenue(BaseModel):
    date: str
    clicks: int
    conversions: int
    estimated_revenue: float
    unique_users: int
    arpu: float


class HealthScore(BaseModel):
    score: int  # 0-100
    grade: str  # A, B, C, D, F
    alerts: list[dict[str, str]]
    metrics: dict[str, RevenueMetric]
    recommendation: str


class PartnerBreakdown(BaseModel):
    partner: str
    clicks: int
    conversions: int
    estimated_revenue: float
    avg_commission: float
    top_ingredients: list[str]
    share_of_revenue: float


# ── Helper Functions ─────────────────────────────────────────────────────────

def _estimate_revenue(provider: str, conversions: int, category: str = "default") -> float:
    """Estimate revenue from a provider based on conversion count."""
    rates = COMMISSION_RATES.get(provider, COMMISSION_RATES["amazon"])

    # CPA partners
    if "cpa" in rates:
        return conversions * rates["cpa"]

    # CPS partners
    aov = AVG_ORDER_VALUES.get(provider, 35.0)
    rate = rates.get(category, rates.get("default", 0.02))
    return conversions * aov * rate


def _health_grade(score: int) -> str:
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 40: return "D"
    return "F"


def _metric_status(actual: float, target: float, higher_is_better: bool = True) -> str:
    ratio = actual / target if target > 0 else 0
    if higher_is_better:
        if ratio >= 1.0: return "green"
        if ratio >= 0.6: return "yellow"
        return "red"
    else:
        if ratio <= 1.0: return "green"
        if ratio <= 1.5: return "yellow"
        return "red"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=RevenueSummary)
async def revenue_summary(
    days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    session: AsyncSession = Depends(get_session),
):
    """Comprehensive revenue summary with ARPU, LTV projections, and partner breakdown."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Unique users in period
    unique_q = select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
        AnalyticsEvent.timestamp >= since,
        AnalyticsEvent.user_id.is_not(None),
    )
    unique_users = (await session.execute(unique_q)).scalar() or 0

    # Affiliate clicks
    clicks_q = select(func.count()).where(
        AnalyticsEvent.event == "affiliate_click",
        AnalyticsEvent.timestamp >= since,
    )
    total_clicks = (await session.execute(clicks_q)).scalar() or 0

    # Affiliate conversions by provider
    conv_q = text("""
        SELECT json_extract(properties, '$.provider') as provider,
               json_extract(properties, '$.category') as category,
               COUNT(*) as conversions,
               COALESCE(SUM(json_extract(properties, '$.order_value')), 0) as total_order_value
        FROM analytics_events
        WHERE event = 'affiliate_conversion' AND timestamp >= :since
        GROUP BY provider
    """)
    try:
        conv_rows = (await session.execute(conv_q, {"since": since})).all()
    except Exception:
        conv_rows = []

    total_conversions = sum(r[2] for r in conv_rows) if conv_rows else 0

    # Estimate revenue per partner
    revenue_by_partner: dict[str, float] = {}
    for row in conv_rows:
        provider = row[0] or "amazon"
        category = row[1] or "default"
        conversions = row[2]
        order_value = row[3] or 0

        if order_value > 0:
            # Use actual order value if reported
            rates = COMMISSION_RATES.get(provider, COMMISSION_RATES["amazon"])
            if "cpa" in rates:
                revenue_by_partner[provider] = conversions * rates["cpa"]
            else:
                rate = rates.get(category, rates.get("default", 0.02))
                revenue_by_partner[provider] = order_value * rate
        else:
            revenue_by_partner[provider] = _estimate_revenue(provider, conversions, category)

    total_revenue = sum(revenue_by_partner.values())

    # ARPU calculation
    monthly_arpu = total_revenue / max(unique_users, 1) * (30 / max(days, 1))

    # CTR and conversion rate
    ctr = total_clicks / max(unique_users, 1) if unique_users > 0 else 0
    conv_rate = total_conversions / max(total_clicks, 1) if total_clicks > 0 else 0

    # Top recipes by affiliate clicks
    top_recipes_q = text("""
        SELECT json_extract(properties, '$.recipe_id') as recipe_id,
               json_extract(properties, '$.recipe_title') as title,
               COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY recipe_id
        ORDER BY clicks DESC
        LIMIT 10
    """)
    try:
        top_rows = (await session.execute(top_recipes_q, {"since": since})).all()
        top_recipes = [{"recipe_id": r[0], "title": r[1], "clicks": r[2]} for r in top_rows]
    except Exception:
        top_recipes = []

    # Prior period for trend
    prior_since = since - timedelta(days=days)
    prior_rev_q = text("""
        SELECT COUNT(*) FROM analytics_events
        WHERE event = 'affiliate_conversion'
        AND timestamp >= :prior_since AND timestamp < :since
    """)
    try:
        prior_convs = (await session.execute(prior_rev_q, {
            "prior_since": prior_since, "since": since
        })).scalar() or 0
    except Exception:
        prior_convs = 0

    arpu_trend = None
    if prior_convs > 0 and total_conversions > 0:
        arpu_trend = round((total_conversions / prior_convs - 1) * 100, 1)

    return RevenueSummary(
        period_days=days,
        total_revenue_est=round(total_revenue, 2),
        arpu=RevenueMetric(
            value=round(monthly_arpu, 4),
            label="Monthly ARPU",
            trend=arpu_trend,
            status=_metric_status(monthly_arpu, TARGETS["arpu_monthly"]),
        ),
        ltv_30d=RevenueMetric(
            value=round(monthly_arpu, 4),
            label="30-Day LTV",
            status=_metric_status(monthly_arpu, TARGETS["arpu_monthly"]),
        ),
        ltv_12m=RevenueMetric(
            value=round(monthly_arpu * 12 * 0.4, 2),  # 40% 12-month retention
            label="12-Month LTV (projected)",
            status=_metric_status(monthly_arpu * 12 * 0.4, TARGETS["arpu_monthly"] * 12 * 0.4),
        ),
        affiliate_ctr=RevenueMetric(
            value=round(ctr, 4),
            label="Affiliate CTR",
            status=_metric_status(ctr, TARGETS["affiliate_ctr"]),
        ),
        conversion_rate=RevenueMetric(
            value=round(conv_rate, 4),
            label="Click-to-Convert Rate",
            status=_metric_status(conv_rate, TARGETS["click_to_convert"]),
        ),
        unique_users=unique_users,
        total_clicks=total_clicks,
        total_conversions=total_conversions,
        revenue_by_partner=revenue_by_partner,
        top_recipes_by_revenue=top_recipes,
    )


@router.get("/daily", response_model=list[DailyRevenue])
async def daily_revenue(
    days: int = Query(30, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
):
    """Daily revenue time series for charting."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily clicks
    clicks_q = text("""
        SELECT DATE(timestamp) as day, COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY day ORDER BY day
    """)

    # Daily conversions
    conv_q = text("""
        SELECT DATE(timestamp) as day,
               COUNT(*) as conversions,
               COALESCE(SUM(json_extract(properties, '$.order_value')), 0) as order_value
        FROM analytics_events
        WHERE event = 'affiliate_conversion' AND timestamp >= :since
        GROUP BY day ORDER BY day
    """)

    # Daily unique users
    users_q = text("""
        SELECT DATE(timestamp) as day,
               COUNT(DISTINCT user_id) as users
        FROM analytics_events
        WHERE timestamp >= :since AND user_id IS NOT NULL
        GROUP BY day ORDER BY day
    """)

    try:
        click_rows = {str(r[0]): r[1] for r in (await session.execute(clicks_q, {"since": since})).all()}
        conv_rows = {str(r[0]): (r[1], r[2]) for r in (await session.execute(conv_q, {"since": since})).all()}
        user_rows = {str(r[0]): r[1] for r in (await session.execute(users_q, {"since": since})).all()}
    except Exception:
        click_rows, conv_rows, user_rows = {}, {}, {}

    # Build daily series
    result = []
    for i in range(days):
        day = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        clicks = click_rows.get(day, 0)
        conversions, order_value = conv_rows.get(day, (0, 0))
        users = user_rows.get(day, 0)

        # Estimate revenue: use actual order value if available, else benchmark
        if order_value > 0:
            est_revenue = order_value * 0.03  # ~3% blended commission
        else:
            est_revenue = _estimate_revenue("amazon", conversions)

        arpu = est_revenue / max(users, 1) if users > 0 else 0

        result.append(DailyRevenue(
            date=day,
            clicks=clicks,
            conversions=conversions,
            estimated_revenue=round(est_revenue, 2),
            unique_users=users,
            arpu=round(arpu, 4),
        ))

    return result


@router.get("/health", response_model=HealthScore)
async def financial_health(
    days: int = Query(7, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
):
    """Financial health score (0-100) with actionable alerts."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Gather key metrics
    unique_q = select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
        AnalyticsEvent.timestamp >= since, AnalyticsEvent.user_id.is_not(None),
    )
    unique_users = (await session.execute(unique_q)).scalar() or 0

    clicks_q = select(func.count()).where(
        AnalyticsEvent.event == "affiliate_click", AnalyticsEvent.timestamp >= since,
    )
    total_clicks = (await session.execute(clicks_q)).scalar() or 0

    conv_q = select(func.count()).where(
        AnalyticsEvent.event == "affiliate_conversion", AnalyticsEvent.timestamp >= since,
    )
    total_conversions = (await session.execute(conv_q)).scalar() or 0

    views_q = select(func.count()).where(
        AnalyticsEvent.event == "recipe_view", AnalyticsEvent.timestamp >= since,
    )
    total_views = (await session.execute(views_q)).scalar() or 0

    # Compute ratios
    ctr = total_clicks / max(unique_users, 1) if unique_users else 0
    conv_rate = total_conversions / max(total_clicks, 1) if total_clicks else 0
    views_per_user = total_views / max(unique_users, 1) if unique_users else 0

    # Score components (0-25 each, total 100)
    scores = {
        "engagement": min(25, int(views_per_user / 5 * 25)),  # Target: 5 views/user
        "monetization_ctr": min(25, int(ctr / TARGETS["affiliate_ctr"] * 25)),
        "conversion": min(25, int(conv_rate / TARGETS["click_to_convert"] * 25)),
        "scale": min(25, int(min(unique_users / 1000, 1) * 25)),  # Target: 1K users
    }
    total_score = sum(scores.values())

    # Build alerts
    alerts = []
    if ctr < TARGETS["affiliate_ctr"] * 0.5:
        alerts.append({
            "level": "critical",
            "message": f"Affiliate CTR is {ctr:.1%} — below 50% of target ({TARGETS['affiliate_ctr']:.0%}). "
                       "Consider: better link placement, 'Shop Ingredients' CTA, recipe-level buy buttons.",
        })
    elif ctr < TARGETS["affiliate_ctr"]:
        alerts.append({
            "level": "warning",
            "message": f"Affiliate CTR is {ctr:.1%} — below target ({TARGETS['affiliate_ctr']:.0%}). "
                       "Try A/B testing link positions or adding ingredient-level buy buttons.",
        })

    if conv_rate < TARGETS["click_to_convert"] * 0.5 and total_clicks > 10:
        alerts.append({
            "level": "critical",
            "message": f"Click-to-convert rate is {conv_rate:.1%}. Check affiliate link quality — "
                       "are links going to relevant products? Consider adding product images/prices.",
        })

    if unique_users < 100 and unique_users > 0:
        alerts.append({
            "level": "info",
            "message": f"Only {unique_users} users in {days}d — too early for reliable metrics. "
                       "Focus on acquisition before optimizing monetization.",
        })

    if unique_users == 0:
        alerts.append({
            "level": "info",
            "message": "No users tracked yet. Revenue analytics will populate once the app is live.",
        })

    if views_per_user < 2 and unique_users > 50:
        alerts.append({
            "level": "warning",
            "message": f"Users viewing only {views_per_user:.1f} recipes on average. "
                       "Improve discovery feed, recommendations, or onboarding.",
        })

    # Recommendation
    if total_score >= 75:
        rec = "Revenue metrics are healthy. Focus on scaling user acquisition."
    elif total_score >= 50:
        rec = "Decent foundation. Prioritize improving affiliate CTR and conversion rate."
    elif total_score >= 25:
        rec = "Early stage. Focus on engagement first — users need to view more recipes before monetization works."
    else:
        rec = "Pre-launch phase. Ship the product, get users, then optimize revenue."

    metrics = {
        "affiliate_ctr": RevenueMetric(
            value=round(ctr, 4), label="Affiliate CTR",
            status=_metric_status(ctr, TARGETS["affiliate_ctr"]),
        ),
        "conversion_rate": RevenueMetric(
            value=round(conv_rate, 4), label="Click → Convert",
            status=_metric_status(conv_rate, TARGETS["click_to_convert"]),
        ),
        "views_per_user": RevenueMetric(
            value=round(views_per_user, 1), label="Views / User",
            status=_metric_status(views_per_user, 5.0),
        ),
        "unique_users": RevenueMetric(
            value=float(unique_users), label="Unique Users",
            status=_metric_status(unique_users, 1000),
        ),
    }

    return HealthScore(
        score=total_score,
        grade=_health_grade(total_score),
        alerts=alerts,
        metrics=metrics,
        recommendation=rec,
    )


@router.get("/partners", response_model=list[PartnerBreakdown])
async def partner_breakdown(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    """Per-partner revenue breakdown."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Clicks by provider
    clicks_q = text("""
        SELECT json_extract(properties, '$.provider') as provider,
               COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY provider ORDER BY clicks DESC
    """)

    # Conversions by provider
    conv_q = text("""
        SELECT json_extract(properties, '$.provider') as provider,
               COUNT(*) as conversions,
               COALESCE(SUM(json_extract(properties, '$.order_value')), 0) as order_value
        FROM analytics_events
        WHERE event = 'affiliate_conversion' AND timestamp >= :since
        GROUP BY provider ORDER BY conversions DESC
    """)

    # Top ingredients clicked by provider
    ing_q = text("""
        SELECT json_extract(properties, '$.provider') as provider,
               json_extract(properties, '$.ingredient') as ingredient,
               COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY provider, ingredient
        ORDER BY provider, clicks DESC
    """)

    try:
        click_rows = {r[0]: r[1] for r in (await session.execute(clicks_q, {"since": since})).all()}
        conv_rows = {r[0]: (r[1], r[2]) for r in (await session.execute(conv_q, {"since": since})).all()}
        ing_rows = (await session.execute(ing_q, {"since": since})).all()
    except Exception:
        click_rows, conv_rows, ing_rows = {}, {}, []

    # Group top ingredients by provider
    provider_ingredients: dict[str, list[str]] = {}
    for row in ing_rows:
        prov = row[0] or "unknown"
        ing = row[1] or "unknown"
        if prov not in provider_ingredients:
            provider_ingredients[prov] = []
        if len(provider_ingredients[prov]) < 5:
            provider_ingredients[prov].append(ing)

    # Build breakdown
    all_providers = set(list(click_rows.keys()) + list(conv_rows.keys()))
    result = []
    total_est_revenue = 0

    for provider in all_providers:
        clicks = click_rows.get(provider, 0)
        conversions, order_value = conv_rows.get(provider, (0, 0))

        if order_value > 0:
            rates = COMMISSION_RATES.get(provider, COMMISSION_RATES["amazon"])
            if "cpa" in rates:
                est_rev = conversions * rates["cpa"]
            else:
                rate = rates.get("default", 0.02)
                est_rev = order_value * rate
        else:
            est_rev = _estimate_revenue(provider, conversions)

        total_est_revenue += est_rev
        avg_comm = est_rev / max(conversions, 1)

        result.append(PartnerBreakdown(
            partner=provider or "unknown",
            clicks=clicks,
            conversions=conversions,
            estimated_revenue=round(est_rev, 2),
            avg_commission=round(avg_comm, 2),
            top_ingredients=provider_ingredients.get(provider, []),
            share_of_revenue=0,  # calculated below
        ))

    # Calculate share of revenue
    for item in result:
        item.share_of_revenue = round(
            item.estimated_revenue / max(total_est_revenue, 0.01) * 100, 1
        )

    result.sort(key=lambda x: x.estimated_revenue, reverse=True)
    return result
