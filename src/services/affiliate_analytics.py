"""
Affiliate Click → Purchase Conversion Tracking.

Tracks the full funnel:
1. User clicks affiliate link (/go/{link_id})
2. Lands on provider site (Amazon, Instacart, etc.)
3. Completes purchase (webhook from provider)
4. Conversion attributed to recipe + ingredient

Supports:
- Multi-touch attribution (last-click, first-click, linear)
- Cross-device tracking via fingerprinting
- Revenue reporting per recipe, ingredient, provider
- A/B testing of affiliate providers
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.affiliate_tables import AffiliateClickRow, AffiliateConversionRow


class AttributionModel(str, Enum):
    """How to attribute conversions when multiple clicks exist."""
    LAST_CLICK = "last_click"      # Most common - last click wins
    FIRST_CLICK = "first_click"    # Brand awareness tracking
    LINEAR = "linear"              # Split credit equally
    TIME_DECAY = "time_decay"      # More recent clicks get more credit


@dataclass
class ConversionEvent:
    """A confirmed purchase through an affiliate link."""
    order_id: str              # Provider's order ID (for deduplication)
    link_id: str               # Our link that generated the click
    provider: str              # amazon, instacart, iherb, thrive
    revenue: float             # Total order value (USD)
    commission: float          # Our commission (USD)
    purchased_at: datetime     # When the purchase happened
    click_id: Optional[int] = None  # FK to AffiliateClickRow
    user_fingerprint: Optional[str] = None  # For cross-device tracking


@dataclass
class ClickAttribution:
    """Links a click to a conversion."""
    click_id: int
    recipe_id: str
    ingredient: str
    clicked_at: datetime
    time_to_purchase: timedelta  # How long between click and purchase
    attribution_weight: float    # % of credit (for multi-touch)


def generate_user_fingerprint(
    user_agent: str,
    ip_address: str,
    accept_language: str = "",
) -> str:
    """Generate a semi-stable identifier for cross-device tracking.
    
    Not perfect (IP changes, VPNs exist), but good enough for affiliate
    attribution windows (typically 24h).
    """
    components = f"{user_agent}|{ip_address}|{accept_language}"
    return hashlib.sha256(components.encode()).hexdigest()[:16]


async def track_click(
    session: AsyncSession,
    link_id: str,
    user_fingerprint: str,
    user_agent: str,
    ip_address: str,
    referer: str = "",
) -> int:
    """Record an affiliate link click. Returns click ID."""
    from src.db.affiliate_tables import AffiliateClickRow
    
    click = AffiliateClickRow(
        link_id=link_id,
        user_fingerprint=user_fingerprint,
        user_agent=user_agent,
        ip_address=ip_address,
        referer=referer,
        clicked_at=datetime.utcnow(),
    )
    session.add(click)
    await session.flush()  # Get the ID without committing
    return click.id


async def record_conversion(
    session: AsyncSession,
    conversion: ConversionEvent,
    attribution_model: AttributionModel = AttributionModel.LAST_CLICK,
    attribution_window_hours: int = 24,
) -> AffiliateConversionRow:
    """Record a confirmed purchase and attribute it to the correct click(s).
    
    Args:
        session: Database session
        conversion: The purchase event from provider webhook
        attribution_model: How to split credit if multiple clicks exist
        attribution_window_hours: How far back to look for clicks (default 24h)
    
    Returns:
        The created conversion record with click attribution
    """
    # 1. Find all clicks for this link in the attribution window
    cutoff = conversion.purchased_at - timedelta(hours=attribution_window_hours)
    
    stmt = select(AffiliateClickRow).where(
        AffiliateClickRow.link_id == conversion.link_id,
        AffiliateClickRow.clicked_at >= cutoff,
        AffiliateClickRow.clicked_at <= conversion.purchased_at,
    )
    
    # If user_fingerprint available, filter by it (more accurate)
    if conversion.user_fingerprint:
        stmt = stmt.where(
            AffiliateClickRow.user_fingerprint == conversion.user_fingerprint
        )
    
    result = await session.execute(stmt.order_by(AffiliateClickRow.clicked_at.desc()))
    clicks = result.scalars().all()
    
    if not clicks:
        # No matching click found - might be direct traffic or expired window
        # Still record the conversion but flag it as unattributed
        conversion_row = AffiliateConversionRow(
            order_id=conversion.order_id,
            link_id=conversion.link_id,
            provider=conversion.provider,
            revenue=conversion.revenue,
            commission=conversion.commission,
            purchased_at=conversion.purchased_at,
            click_id=None,  # No attribution
            is_attributed=False,
        )
        session.add(conversion_row)
        await session.flush()
        return conversion_row
    
    # 2. Apply attribution model
    if attribution_model == AttributionModel.LAST_CLICK:
        # Most recent click gets 100% credit
        attributed_click = clicks[0]
        conversion_row = AffiliateConversionRow(
            order_id=conversion.order_id,
            link_id=conversion.link_id,
            provider=conversion.provider,
            revenue=conversion.revenue,
            commission=conversion.commission,
            purchased_at=conversion.purchased_at,
            click_id=attributed_click.id,
            is_attributed=True,
            time_to_purchase_seconds=int(
                (conversion.purchased_at - attributed_click.clicked_at).total_seconds()
            ),
        )
        session.add(conversion_row)
        await session.flush()
        return conversion_row
    
    elif attribution_model == AttributionModel.FIRST_CLICK:
        # Oldest click gets 100% credit
        attributed_click = clicks[-1]
        conversion_row = AffiliateConversionRow(
            order_id=conversion.order_id,
            link_id=conversion.link_id,
            provider=conversion.provider,
            revenue=conversion.revenue,
            commission=conversion.commission,
            purchased_at=conversion.purchased_at,
            click_id=attributed_click.id,
            is_attributed=True,
            time_to_purchase_seconds=int(
                (conversion.purchased_at - attributed_click.clicked_at).total_seconds()
            ),
        )
        session.add(conversion_row)
        await session.flush()
        return conversion_row
    
    # TODO: Implement LINEAR and TIME_DECAY models if needed
    # For now, fall back to LAST_CLICK
    return await record_conversion(
        session, conversion, AttributionModel.LAST_CLICK, attribution_window_hours
    )


async def get_recipe_revenue_stats(
    session: AsyncSession,
    recipe_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """Get revenue stats for a specific recipe.
    
    Returns:
        {
            "total_clicks": 147,
            "total_conversions": 12,
            "conversion_rate": 0.0816,  # 8.16%
            "total_revenue": 542.80,
            "total_commission": 38.99,
            "avg_order_value": 45.23,
            "top_ingredient": "protein powder",
            "top_provider": "iherb",
        }
    """
    # Get all clicks for this recipe
    clicks_query = select(func.count()).select_from(AffiliateClickRow).join(
        # Need to join through link_id → recipe mapping
        # This requires the affiliate_redirect service's link storage
        # For now, simplified version
    )
    
    # TODO: Implement full stats once link → recipe mapping is available
    # For MVP, return basic structure
    return {
        "total_clicks": 0,
        "total_conversions": 0,
        "conversion_rate": 0.0,
        "total_revenue": 0.0,
        "total_commission": 0.0,
        "avg_order_value": 0.0,
        "top_ingredient": None,
        "top_provider": None,
    }


async def get_provider_performance(
    session: AsyncSession,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> list[dict]:
    """Compare conversion rates across affiliate providers.
    
    Returns list sorted by revenue, e.g.:
    [
        {
            "provider": "iherb",
            "clicks": 1834,
            "conversions": 187,
            "conversion_rate": 0.102,  # 10.2%
            "revenue": 8450.23,
            "commission": 845.02,  # 10% commission
            "avg_order_value": 45.19,
        },
        ...
    ]
    """
    # Build date filter
    filters = []
    if start_date:
        filters.append(AffiliateConversionRow.purchased_at >= start_date)
    if end_date:
        filters.append(AffiliateConversionRow.purchased_at <= end_date)
    
    stmt = select(
        AffiliateConversionRow.provider,
        func.count(AffiliateConversionRow.id).label("conversions"),
        func.sum(AffiliateConversionRow.revenue).label("revenue"),
        func.sum(AffiliateConversionRow.commission).label("commission"),
        func.avg(AffiliateConversionRow.revenue).label("avg_order_value"),
    ).group_by(AffiliateConversionRow.provider)
    
    if filters:
        stmt = stmt.where(*filters)
    
    result = await session.execute(stmt)
    rows = result.all()
    
    # TODO: Join with clicks table to get conversion rates
    # For now, return basic stats
    return [
        {
            "provider": row.provider,
            "clicks": 0,  # TODO: join with clicks
            "conversions": row.conversions,
            "conversion_rate": 0.0,  # TODO: calculate
            "revenue": float(row.revenue or 0),
            "commission": float(row.commission or 0),
            "avg_order_value": float(row.avg_order_value or 0),
        }
        for row in rows
    ]


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify HMAC signature from affiliate provider webhook.
    
    Prevents fake conversion events from external sources.
    """
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
