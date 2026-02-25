"""
Affiliate admin dashboard endpoints.

Real-time analytics and monitoring for affiliate revenue performance.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.services.affiliate_monitoring import (
    get_affiliate_health,
    detect_fraudulent_conversions,
    send_daily_revenue_report,
)
from src.services.affiliate_analytics import get_provider_performance

router = APIRouter(prefix="/api/v1/admin/affiliate", tags=["Affiliate Admin"])
logger = logging.getLogger(__name__)


class AffiliateHealthResponse(BaseModel):
    """Current affiliate system health."""
    clicks_24h: int
    conversions_24h: int
    revenue_24h: float
    conversion_rate_24h: float
    avg_order_value_24h: float
    
    clicks_7d_avg: int
    conversions_7d_avg: int
    revenue_7d_avg: float
    conversion_rate_7d_avg: float
    
    # Alerts
    alerts: list[str]


class ProviderPerformanceResponse(BaseModel):
    """Performance comparison across providers."""
    provider: str
    clicks: int
    conversions: int
    conversion_rate: float
    revenue: float
    commission: float
    avg_order_value: float


class FraudDetectionResponse(BaseModel):
    """Suspicious conversion patterns."""
    type: str
    details: dict
    explanation: str


@router.get("/health", response_model=AffiliateHealthResponse)
async def get_health_dashboard(
    session: AsyncSession = Depends(get_session),
):
    """Get real-time affiliate system health metrics.
    
    Returns:
        Current 24h metrics, 7d averages, and any active alerts
    """
    metrics = await get_affiliate_health(session)
    
    # Build alerts list
    alerts = []
    if metrics.conversion_rate_drop:
        alerts.append(
            f"⚠️ Conversion rate dropped {(metrics.conversion_rate_7d_avg - metrics.conversion_rate_24h) / metrics.conversion_rate_7d_avg * 100:.1f}% vs 7d avg"
        )
    if metrics.revenue_drop:
        alerts.append(
            f"🚨 Revenue dropped {(metrics.revenue_7d_avg - metrics.revenue_24h) / metrics.revenue_7d_avg * 100:.1f}% vs 7d avg"
        )
    if metrics.zero_conversions:
        alerts.append(
            f"🔴 ZERO conversions in 24h despite {metrics.clicks_24h} clicks - tracking may be broken"
        )
    if metrics.unusually_high_clicks:
        alerts.append(
            f"⚠️ Unusually high click volume ({metrics.clicks_24h} vs {metrics.clicks_7d_avg} avg) - possible bot traffic"
        )
    
    return AffiliateHealthResponse(
        clicks_24h=metrics.clicks_24h,
        conversions_24h=metrics.conversions_24h,
        revenue_24h=metrics.revenue_24h,
        conversion_rate_24h=metrics.conversion_rate_24h,
        avg_order_value_24h=metrics.avg_order_value_24h,
        clicks_7d_avg=metrics.clicks_7d_avg,
        conversions_7d_avg=metrics.conversions_7d_avg,
        revenue_7d_avg=metrics.revenue_7d_avg,
        conversion_rate_7d_avg=metrics.conversion_rate_7d_avg,
        alerts=alerts,
    )


@router.get("/providers", response_model=list[ProviderPerformanceResponse])
async def get_provider_performance_comparison(
    session: AsyncSession = Depends(get_session),
):
    """Compare conversion performance across affiliate providers.
    
    Returns:
        List of providers sorted by revenue
    """
    providers = await get_provider_performance(session)
    
    return [
        ProviderPerformanceResponse(
            provider=p["provider"],
            clicks=p["clicks"],
            conversions=p["conversions"],
            conversion_rate=p["conversion_rate"],
            revenue=p["revenue"],
            commission=p["commission"],
            avg_order_value=p["avg_order_value"],
        )
        for p in providers
    ]


@router.get("/fraud-detection", response_model=list[FraudDetectionResponse])
async def detect_fraud(
    lookback_hours: int = 24,
    session: AsyncSession = Depends(get_session),
):
    """Detect suspicious conversion patterns (fraud, bots, testing).
    
    Args:
        lookback_hours: How far back to scan (default 24h)
    
    Returns:
        List of suspicious events with explanations
    """
    suspicious = await detect_fraudulent_conversions(session, lookback_hours)
    
    return [
        FraudDetectionResponse(
            type=event["type"],
            details={k: v for k, v in event.items() if k not in ("type", "explanation")},
            explanation=event["explanation"],
        )
        for event in suspicious
    ]


@router.get("/daily-report")
async def get_daily_report(
    session: AsyncSession = Depends(get_session),
):
    """Generate daily revenue report (HTML email format).
    
    Returns:
        HTML email body with daily revenue stats
    """
    metrics = await get_affiliate_health(session)
    html = send_daily_revenue_report(metrics)
    
    return {
        "html": html,
        "subject": f"FitBites Affiliate Revenue: ${metrics.revenue_24h:,.2f} (last 24h)",
        "metrics": {
            "revenue_24h": metrics.revenue_24h,
            "conversions_24h": metrics.conversions_24h,
            "conversion_rate_24h": metrics.conversion_rate_24h,
        },
    }
