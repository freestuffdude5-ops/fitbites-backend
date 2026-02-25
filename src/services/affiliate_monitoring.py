"""
Affiliate revenue monitoring and alerting.

Sends alerts when:
- Conversion rate drops significantly (potential tracking issue)
- Revenue drops day-over-day (affiliate account issue)
- Webhook failures exceed threshold (integration broken)
- Suspicious activity detected (fraud, bot traffic)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.affiliate_tables import AffiliateClickRow, AffiliateConversionRow

logger = logging.getLogger(__name__)


@dataclass
class AffiliateHealthMetrics:
    """Current health metrics for affiliate system."""
    clicks_24h: int
    conversions_24h: int
    revenue_24h: float
    conversion_rate_24h: float
    avg_order_value_24h: float
    
    clicks_7d_avg: int
    conversions_7d_avg: int
    revenue_7d_avg: float
    conversion_rate_7d_avg: float
    
    # Anomaly flags
    conversion_rate_drop: bool  # >30% drop from 7d avg
    revenue_drop: bool  # >40% drop from 7d avg
    zero_conversions: bool  # No conversions in 24h (tracking broken?)
    unusually_high_clicks: bool  # >3x normal (potential bot attack)


async def get_affiliate_health(
    session: AsyncSession,
) -> AffiliateHealthMetrics:
    """Calculate current affiliate system health metrics."""
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    
    # --- 24h metrics ---
    clicks_24h_stmt = select(func.count()).select_from(AffiliateClickRow).where(
        AffiliateClickRow.clicked_at >= last_24h
    )
    clicks_24h = (await session.execute(clicks_24h_stmt)).scalar() or 0
    
    conversions_24h_stmt = select(
        func.count(),
        func.sum(AffiliateConversionRow.revenue),
    ).select_from(AffiliateConversionRow).where(
        AffiliateConversionRow.purchased_at >= last_24h
    )
    result_24h = (await session.execute(conversions_24h_stmt)).one()
    conversions_24h = result_24h[0] or 0
    revenue_24h = float(result_24h[1] or 0)
    
    conversion_rate_24h = (
        (conversions_24h / clicks_24h) if clicks_24h > 0 else 0.0
    )
    avg_order_value_24h = (
        (revenue_24h / conversions_24h) if conversions_24h > 0 else 0.0
    )
    
    # --- 7d averages (for comparison) ---
    clicks_7d_stmt = select(func.count()).select_from(AffiliateClickRow).where(
        AffiliateClickRow.clicked_at >= last_7d
    )
    clicks_7d = (await session.execute(clicks_7d_stmt)).scalar() or 0
    clicks_7d_avg = clicks_7d // 7
    
    conversions_7d_stmt = select(
        func.count(),
        func.sum(AffiliateConversionRow.revenue),
    ).select_from(AffiliateConversionRow).where(
        AffiliateConversionRow.purchased_at >= last_7d
    )
    result_7d = (await session.execute(conversions_7d_stmt)).one()
    conversions_7d = result_7d[0] or 0
    revenue_7d = float(result_7d[1] or 0)
    
    conversions_7d_avg = conversions_7d // 7
    revenue_7d_avg = revenue_7d / 7
    conversion_rate_7d_avg = (
        (conversions_7d / clicks_7d) if clicks_7d > 0 else 0.0
    )
    
    # --- Anomaly detection ---
    conversion_rate_drop = False
    if conversion_rate_7d_avg > 0:
        drop_pct = (conversion_rate_7d_avg - conversion_rate_24h) / conversion_rate_7d_avg
        conversion_rate_drop = drop_pct > 0.3  # >30% drop
    
    revenue_drop = False
    if revenue_7d_avg > 0:
        drop_pct = (revenue_7d_avg - revenue_24h) / revenue_7d_avg
        revenue_drop = drop_pct > 0.4  # >40% drop
    
    zero_conversions = (conversions_24h == 0 and clicks_24h > 50)
    
    unusually_high_clicks = (
        clicks_7d_avg > 0 and clicks_24h > (clicks_7d_avg * 3)
    )
    
    return AffiliateHealthMetrics(
        clicks_24h=clicks_24h,
        conversions_24h=conversions_24h,
        revenue_24h=revenue_24h,
        conversion_rate_24h=conversion_rate_24h,
        avg_order_value_24h=avg_order_value_24h,
        clicks_7d_avg=clicks_7d_avg,
        conversions_7d_avg=conversions_7d_avg,
        revenue_7d_avg=revenue_7d_avg,
        conversion_rate_7d_avg=conversion_rate_7d_avg,
        conversion_rate_drop=conversion_rate_drop,
        revenue_drop=revenue_drop,
        zero_conversions=zero_conversions,
        unusually_high_clicks=unusually_high_clicks,
    )


async def check_affiliate_health_and_alert(
    session: AsyncSession,
    send_alert_fn: callable = None,
) -> AffiliateHealthMetrics:
    """Check affiliate health and send alerts if issues detected.
    
    Args:
        session: Database session
        send_alert_fn: Function to send alerts (email, Slack, etc.)
            Signature: async def send_alert(title: str, message: str, severity: str)
    
    Returns:
        Current health metrics
    """
    metrics = await get_affiliate_health(session)
    
    alerts = []
    
    if metrics.conversion_rate_drop:
        alerts.append({
            "title": "⚠️ Conversion Rate Dropped 30%+",
            "message": (
                f"Conversion rate dropped from {metrics.conversion_rate_7d_avg:.2%} (7d avg) "
                f"to {metrics.conversion_rate_24h:.2%} (last 24h).\n\n"
                f"Possible causes:\n"
                f"- Affiliate tracking broken\n"
                f"- Cookie issues on provider side\n"
                f"- Link ID generation bug\n"
                f"- Users clicking but not converting (UX issue)"
            ),
            "severity": "high",
        })
    
    if metrics.revenue_drop:
        alerts.append({
            "title": "🚨 Revenue Dropped 40%+",
            "message": (
                f"Revenue dropped from ${metrics.revenue_7d_avg:.2f} (7d avg) "
                f"to ${metrics.revenue_24h:.2f} (last 24h).\n\n"
                f"Possible causes:\n"
                f"- Provider webhook not firing\n"
                f"- Affiliate account suspended\n"
                f"- Commission rate changed\n"
                f"- Product availability issues"
            ),
            "severity": "critical",
        })
    
    if metrics.zero_conversions:
        alerts.append({
            "title": "🔴 ZERO Conversions (Tracking Broken?)",
            "message": (
                f"Got {metrics.clicks_24h} clicks in last 24h but ZERO conversions.\n\n"
                f"This is highly unusual (expected ~{int(metrics.clicks_24h * metrics.conversion_rate_7d_avg)} conversions).\n\n"
                f"ACTION REQUIRED:\n"
                f"1. Check webhook endpoints are receiving POST requests\n"
                f"2. Verify HMAC signature validation isn't rejecting valid webhooks\n"
                f"3. Test conversion recording manually\n"
                f"4. Check provider dashboard for conversions (they may not be sending webhooks)"
            ),
            "severity": "critical",
        })
    
    if metrics.unusually_high_clicks:
        alerts.append({
            "title": "⚠️ Unusually High Clicks (Bot Traffic?)",
            "message": (
                f"Got {metrics.clicks_24h} clicks in last 24h (3x normal).\n\n"
                f"This could indicate:\n"
                f"- Bot attack (invalid traffic, won't convert)\n"
                f"- Viral recipe (legit traffic spike)\n"
                f"- Referral spam\n\n"
                f"Monitor conversion rate - if it stays normal, traffic is legit."
            ),
            "severity": "medium",
        })
    
    # Send alerts if function provided
    if send_alert_fn and alerts:
        for alert in alerts:
            try:
                await send_alert_fn(
                    title=alert["title"],
                    message=alert["message"],
                    severity=alert["severity"],
                )
            except Exception as e:
                logger.exception(f"Failed to send alert: {alert['title']}")
    
    # Log metrics even if no alerts
    logger.info(
        f"Affiliate health check: {metrics.clicks_24h} clicks, "
        f"{metrics.conversions_24h} conversions ({metrics.conversion_rate_24h:.2%}), "
        f"${metrics.revenue_24h:.2f} revenue"
    )
    
    return metrics


async def detect_fraudulent_conversions(
    session: AsyncSession,
    lookback_hours: int = 24,
) -> list[dict]:
    """Detect suspicious conversion patterns that might indicate fraud.
    
    Returns:
        List of suspicious conversion events with explanations
    """
    suspicious = []
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=lookback_hours)
    
    # Pattern 1: Multiple conversions from same user_fingerprint in short time
    duplicates_stmt = select(
        AffiliateClickRow.user_fingerprint,
        func.count(AffiliateConversionRow.id).label("conversion_count"),
    ).select_from(AffiliateClickRow).join(
        AffiliateConversionRow,
        AffiliateClickRow.id == AffiliateConversionRow.click_id,
    ).where(
        AffiliateConversionRow.purchased_at >= cutoff
    ).group_by(
        AffiliateClickRow.user_fingerprint
    ).having(
        func.count(AffiliateConversionRow.id) > 3
    )
    
    duplicates = (await session.execute(duplicates_stmt)).all()
    
    for row in duplicates:
        suspicious.append({
            "type": "duplicate_user",
            "user_fingerprint": row.user_fingerprint,
            "conversion_count": row.conversion_count,
            "explanation": (
                f"Same user fingerprint made {row.conversion_count} purchases in "
                f"{lookback_hours}h (unusual, might be testing or fraud)"
            ),
        })
    
    # Pattern 2: Conversions with suspiciously short time-to-purchase
    fast_conversions_stmt = select(AffiliateConversionRow).where(
        AffiliateConversionRow.purchased_at >= cutoff,
        AffiliateConversionRow.time_to_purchase_seconds < 30,  # <30 seconds (impossible)
    )
    
    fast_conversions = (await session.execute(fast_conversions_stmt)).scalars().all()
    
    for conv in fast_conversions:
        suspicious.append({
            "type": "instant_conversion",
            "order_id": conv.order_id,
            "time_to_purchase": conv.time_to_purchase_seconds,
            "explanation": (
                f"Purchase completed {conv.time_to_purchase_seconds}s after click "
                f"(too fast to be real - likely bot or testing)"
            ),
        })
    
    # Pattern 3: Unusually high order values (potential refund fraud)
    high_value_stmt = select(AffiliateConversionRow).where(
        AffiliateConversionRow.purchased_at >= cutoff,
        AffiliateConversionRow.revenue > 500,  # >$500 order (rare for grocery app)
    )
    
    high_value = (await session.execute(high_value_stmt)).scalars().all()
    
    for conv in high_value:
        suspicious.append({
            "type": "high_value_order",
            "order_id": conv.order_id,
            "revenue": conv.revenue,
            "explanation": (
                f"${conv.revenue:.2f} order (unusually high for grocery recipes - "
                f"monitor for refund/chargeback)"
            ),
        })
    
    return suspicious


def send_daily_revenue_report(
    metrics: AffiliateHealthMetrics,
) -> str:
    """Generate a daily revenue report email body.
    
    Returns:
        HTML email body with revenue stats
    """
    # Calculate change vs 7d average
    conv_rate_change = (
        ((metrics.conversion_rate_24h - metrics.conversion_rate_7d_avg) 
         / metrics.conversion_rate_7d_avg * 100)
        if metrics.conversion_rate_7d_avg > 0 else 0
    )
    
    revenue_change = (
        ((metrics.revenue_24h - metrics.revenue_7d_avg) 
         / metrics.revenue_7d_avg * 100)
        if metrics.revenue_7d_avg > 0 else 0
    )
    
    conv_rate_icon = "📈" if conv_rate_change > 0 else "📉"
    revenue_icon = "📈" if revenue_change > 0 else "📉"
    
    html = f"""
    <h2>FitBites Affiliate Revenue Report</h2>
    <p><strong>Last 24 Hours</strong></p>
    <table style="border-collapse: collapse; width: 100%;">
        <tr style="background: #f5f5f5;">
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Clicks</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;">{metrics.clicks_24h:,}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Conversions</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;">{metrics.conversions_24h:,}</td>
        </tr>
        <tr style="background: #f5f5f5;">
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Conversion Rate</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {conv_rate_icon} {metrics.conversion_rate_24h:.2%} 
                ({conv_rate_change:+.1f}% vs 7d avg)
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Revenue</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {revenue_icon} ${metrics.revenue_24h:,.2f} 
                ({revenue_change:+.1f}% vs 7d avg)
            </td>
        </tr>
        <tr style="background: #f5f5f5;">
            <td style="padding: 8px; border: 1px solid #ddd;"><strong>Avg Order Value</strong></td>
            <td style="padding: 8px; border: 1px solid #ddd;">${metrics.avg_order_value_24h:.2f}</td>
        </tr>
    </table>
    
    <p style="margin-top: 20px;"><strong>7-Day Averages</strong></p>
    <ul>
        <li>Clicks/day: {metrics.clicks_7d_avg:,}</li>
        <li>Conversions/day: {metrics.conversions_7d_avg:,}</li>
        <li>Revenue/day: ${metrics.revenue_7d_avg:,.2f}</li>
        <li>Conversion rate: {metrics.conversion_rate_7d_avg:.2%}</li>
    </ul>
    """
    
    return html
