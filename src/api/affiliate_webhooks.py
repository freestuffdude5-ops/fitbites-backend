"""
Affiliate conversion webhook endpoints.

Receives POST requests from affiliate providers (Amazon, Impact, etc.)
when a purchase is completed, allowing us to track conversions and revenue.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.db.engine import get_session
from src.services.affiliate_analytics import (
    ConversionEvent,
    record_conversion,
    verify_webhook_signature,
)

router = APIRouter(prefix="/api/v1/webhooks/affiliate", tags=["Affiliate Webhooks"])
logger = logging.getLogger(__name__)


class AmazonConversionWebhook(BaseModel):
    """Amazon Associates conversion event (simplified)."""
    order_id: str
    link_id: str  # Extracted from tracking tag
    total_amount: float
    commission: float
    purchase_date: str  # ISO8601


class ImpactConversionWebhook(BaseModel):
    """Impact.com conversion event (Instacart, Walmart use this)."""
    event_type: str  # "CONVERSION"
    order_id: str
    click_id: str  # Their internal click ID
    subid1: str  # We encode our link_id here
    amount: float
    payout: float
    event_date: str  # ISO8601


@router.post("/amazon")
async def amazon_conversion_webhook(
    webhook: AmazonConversionWebhook,
    session: AsyncSession = Depends(get_session),
    x_amz_signature: str = Header(None),
):
    """Receive conversion events from Amazon Associates.
    
    Note: Amazon doesn't have official webhooks. This is a placeholder
    for future integration if they add it, or for manual import from reports.
    """
    # Verify signature
    if settings.AMAZON_WEBHOOK_SECRET:
        # TODO: Implement Amazon's signature verification once they support it
        pass
    
    # Parse conversion
    conversion = ConversionEvent(
        order_id=webhook.order_id,
        link_id=webhook.link_id,
        provider="amazon",
        revenue=webhook.total_amount,
        commission=webhook.commission,
        purchased_at=datetime.fromisoformat(webhook.purchase_date.replace("Z", "+00:00")),
    )
    
    # Record in database
    result = await record_conversion(session, conversion)
    await session.commit()
    
    logger.info(
        f"Amazon conversion recorded: order={webhook.order_id}, "
        f"revenue=${webhook.total_amount}, commission=${webhook.commission}"
    )
    
    return {"status": "recorded", "conversion_id": result.id}


@router.post("/impact")
async def impact_conversion_webhook(
    request: Request,
    webhook: ImpactConversionWebhook,
    session: AsyncSession = Depends(get_session),
):
    """Receive conversion events from Impact.com (Instacart, Walmart, etc.)."""
    # Verify signature
    if settings.IMPACT_WEBHOOK_SECRET:
        body = await request.body()
        signature = request.headers.get("X-Impact-Signature", "")
        
        if not verify_webhook_signature(
            body,
            signature,
            settings.IMPACT_WEBHOOK_SECRET,
        ):
            logger.warning(f"Invalid Impact webhook signature: {signature[:20]}...")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Extract our link_id from subid1
    link_id = webhook.subid1
    
    # Parse conversion
    conversion = ConversionEvent(
        order_id=webhook.order_id,
        link_id=link_id,
        provider="impact",  # Could be instacart, walmart, etc.
        revenue=webhook.amount,
        commission=webhook.payout,
        purchased_at=datetime.fromisoformat(webhook.event_date.replace("Z", "+00:00")),
    )
    
    # Record in database
    result = await record_conversion(session, conversion)
    await session.commit()
    
    logger.info(
        f"Impact conversion recorded: order={webhook.order_id}, "
        f"revenue=${webhook.amount}, commission=${webhook.payout}"
    )
    
    return {"status": "recorded", "conversion_id": result.id}


@router.post("/generic")
async def generic_conversion_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Generic webhook receiver for any provider.
    
    Accepts JSON payload with standard fields:
    {
        "order_id": "ABC123",
        "link_id": "a3f8b2c1",
        "provider": "iherb",
        "revenue": 45.99,
        "commission": 4.60,
        "purchased_at": "2026-02-24T12:00:00Z"
    }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Verify signature if secret is configured
    if settings.AFFILIATE_WEBHOOK_SECRET:
        body = await request.body()
        signature = request.headers.get("X-FitBites-Signature", "")
        
        if not verify_webhook_signature(
            body,
            signature,
            settings.AFFILIATE_WEBHOOK_SECRET,
        ):
            logger.warning(f"Invalid webhook signature from {request.client.host}")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Validate required fields
    required = ["order_id", "link_id", "provider", "revenue", "commission", "purchased_at"]
    missing = [f for f in required if f not in data]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {', '.join(missing)}"
        )
    
    # Parse conversion
    conversion = ConversionEvent(
        order_id=data["order_id"],
        link_id=data["link_id"],
        provider=data["provider"],
        revenue=float(data["revenue"]),
        commission=float(data["commission"]),
        purchased_at=datetime.fromisoformat(data["purchased_at"].replace("Z", "+00:00")),
    )
    
    # Record in database
    result = await record_conversion(session, conversion)
    await session.commit()
    
    logger.info(
        f"{data['provider']} conversion recorded: order={data['order_id']}, "
        f"revenue=${data['revenue']}, commission=${data['commission']}"
    )
    
    return {"status": "recorded", "conversion_id": result.id}
