"""
FitBites Subscription Service
---
Manages subscription lifecycle across Stripe (web) and Apple IAP (iOS).
Single source of truth for user entitlements.

Endpoints:
- POST /api/v1/subscriptions/stripe/webhook — Stripe webhook handler
- POST /api/v1/subscriptions/apple/verify — Apple receipt validation
- GET  /api/v1/subscriptions/me — Current user's subscription status
- POST /api/v1/subscriptions/stripe/create-checkout — Create Stripe checkout session
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.subscription_tables import SubscriptionRow, PaymentEventRow
from src.db.user_tables import UserRow
from src.auth import require_user
from src.services.pricing import Tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])

# ── Config ────────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET", "")
APPLE_BUNDLE_ID = "com.83apps.fitbites"

# Apple StoreKit2 / App Store Server API
APPLE_VERIFY_URL_PROD = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_VERIFY_URL_SANDBOX = "https://sandbox.itunes.apple.com/verifyReceipt"

# Map Apple product IDs → tiers
APPLE_PRODUCT_TIER_MAP = {
    "com.83apps.fitbites.pro.monthly": (Tier.PRO, "monthly"),
    "com.83apps.fitbites.pro.annual": (Tier.PRO, "annual"),
    "com.83apps.fitbites.proplus.monthly": (Tier.PRO_PLUS, "monthly"),
    "com.83apps.fitbites.proplus.annual": (Tier.PRO_PLUS, "annual"),
}

# Map Stripe price IDs → tiers (populated after Stripe setup)
STRIPE_PRICE_TIER_MAP: dict[str, tuple[Tier, str]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms_to_dt(ms: int | str) -> datetime:
    """Convert millisecond timestamp to datetime."""
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


async def _get_or_create_subscription(
    session: AsyncSession, user_id: str
) -> SubscriptionRow:
    """Get existing subscription or create a free one."""
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        sub = SubscriptionRow(id=str(uuid.uuid4()), user_id=user_id, tier="free", status="active")
        session.add(sub)
        await session.flush()
    return sub


async def _log_payment_event(
    session: AsyncSession,
    user_id: str | None,
    subscription_id: str | None,
    event_type: str,
    source: str,
    payload: dict | None = None,
    amount_cents: float | None = None,
) -> None:
    """Write immutable payment event log."""
    event = PaymentEventRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        subscription_id=subscription_id,
        event_type=event_type,
        source=source,
        payload=payload,
        amount_cents=amount_cents,
    )
    session.add(event)


# ── Stripe ────────────────────────────────────────────────────────────────────

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify Stripe webhook signature and return parsed event.
    
    Follows Stripe's v1 signature verification:
    1. Extract timestamp and signatures from header
    2. Compute expected signature using HMAC-SHA256
    3. Compare (timing-safe) and check timestamp tolerance
    """
    if not secret:
        raise HTTPException(500, "Stripe webhook secret not configured")

    try:
        elements = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = elements.get("t", "")
        signature = elements.get("v1", "")
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid Stripe signature header")

    if not timestamp or not signature:
        raise HTTPException(400, "Missing timestamp or signature")

    # Check timestamp tolerance (5 minutes)
    if abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(400, "Webhook timestamp too old")

    # Compute expected signature
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(400, "Invalid signature")

    return json.loads(payload)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="stripe-signature"),
    session: AsyncSession = Depends(get_session),
):
    """Handle Stripe webhook events for subscription lifecycle.
    
    Handles:
    - checkout.session.completed → New subscription
    - customer.subscription.updated → Plan changes, renewals
    - customer.subscription.deleted → Cancellation
    - invoice.paid → Successful payment
    - invoice.payment_failed → Payment failure
    - charge.refunded → Refund processing
    """
    body = await request.body()
    event = _verify_stripe_signature(body, stripe_signature, STRIPE_WEBHOOK_SECRET)

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    logger.info(f"Stripe webhook: {event_type}")

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(session, data, event)

    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(session, data, event)

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(session, data, event)

    elif event_type == "invoice.paid":
        await _handle_invoice_paid(session, data, event)

    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(session, data, event)

    elif event_type == "charge.refunded":
        await _handle_refund(session, data, event)

    else:
        logger.debug(f"Unhandled Stripe event: {event_type}")

    await session.commit()
    return {"status": "ok"}


async def _handle_checkout_completed(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """New subscription created via Stripe Checkout."""
    user_id = data.get("client_reference_id")  # We set this when creating the session
    stripe_sub_id = data.get("subscription")
    stripe_customer_id = data.get("customer")

    if not user_id or not stripe_sub_id:
        logger.warning("Checkout completed but missing user_id or subscription")
        return

    sub = await _get_or_create_subscription(session, user_id)

    # Determine tier from metadata or line items
    metadata = data.get("metadata", {})
    tier_str = metadata.get("tier", "pro")
    billing = metadata.get("billing_period", "monthly")

    sub.tier = tier_str
    sub.billing_period = billing
    sub.platform = "web"
    sub.status = "active"
    sub.stripe_subscription_id = stripe_sub_id
    sub.stripe_customer_id = stripe_customer_id
    sub.started_at = _now()
    sub.updated_at = _now()
    sub.experiment_id = metadata.get("experiment_id")
    sub.variant_id = metadata.get("variant_id")
    sub.price_paid = float(data.get("amount_total", 0)) / 100

    await _log_payment_event(
        session, user_id, sub.id, "checkout.session.completed", "stripe",
        payload={"stripe_sub_id": stripe_sub_id, "tier": tier_str},
        amount_cents=data.get("amount_total"),
    )
    logger.info(f"New Stripe subscription: user={user_id} tier={tier_str}")


async def _handle_subscription_updated(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """Subscription plan changed or renewed."""
    stripe_sub_id = data.get("id")
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning(f"Subscription update for unknown stripe sub: {stripe_sub_id}")
        return

    status = data.get("status", "active")
    status_map = {
        "active": "active",
        "past_due": "past_due",
        "canceled": "canceled",
        "trialing": "trialing",
        "unpaid": "past_due",
    }
    sub.status = status_map.get(status, status)

    period = data.get("current_period_end")
    if period:
        sub.current_period_end = datetime.fromtimestamp(period, tz=timezone.utc)
    period_start = data.get("current_period_start")
    if period_start:
        sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)

    if data.get("cancel_at_period_end"):
        sub.canceled_at = _now()
        sub.status = "canceled"

    sub.updated_at = _now()

    await _log_payment_event(
        session, sub.user_id, sub.id, "subscription.updated", "stripe",
        payload={"status": sub.status, "stripe_sub_id": stripe_sub_id},
    )


async def _handle_subscription_deleted(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """Subscription fully canceled/expired."""
    stripe_sub_id = data.get("id")
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.tier = "free"
    sub.status = "expired"
    sub.canceled_at = _now()
    sub.updated_at = _now()

    await _log_payment_event(
        session, sub.user_id, sub.id, "subscription.deleted", "stripe",
        payload={"stripe_sub_id": stripe_sub_id},
    )
    logger.info(f"Subscription expired: user={sub.user_id}")


async def _handle_invoice_paid(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """Successful payment — log for revenue tracking."""
    stripe_sub_id = data.get("subscription")
    amount = data.get("amount_paid", 0)

    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    user_id = sub.user_id if sub else None

    await _log_payment_event(
        session, user_id, sub.id if sub else None,
        "invoice.paid", "stripe",
        payload={"invoice_id": data.get("id"), "stripe_sub_id": stripe_sub_id},
        amount_cents=amount,
    )


async def _handle_payment_failed(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """Payment failed — mark subscription as past_due."""
    stripe_sub_id = data.get("subscription")
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if sub:
        sub.status = "past_due"
        sub.updated_at = _now()

    await _log_payment_event(
        session, sub.user_id if sub else None, sub.id if sub else None,
        "invoice.payment_failed", "stripe",
        payload={"stripe_sub_id": stripe_sub_id},
    )
    logger.warning(f"Payment failed: stripe_sub={stripe_sub_id}")


async def _handle_refund(
    session: AsyncSession, data: dict, event: dict
) -> None:
    """Refund processed."""
    amount = data.get("amount_refunded", 0)
    customer = data.get("customer")

    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.stripe_customer_id == customer)
    )
    sub = result.scalar_one_or_none()

    await _log_payment_event(
        session, sub.user_id if sub else None, sub.id if sub else None,
        "charge.refunded", "stripe",
        payload={"charge_id": data.get("id"), "amount_refunded": amount},
        amount_cents=-amount,  # Negative for refunds
    )


# ── Apple IAP ─────────────────────────────────────────────────────────────────

class AppleReceiptRequest(BaseModel):
    receipt_data: str  # Base64-encoded receipt
    user_id: str


@router.post("/apple/verify")
async def verify_apple_receipt(
    req: AppleReceiptRequest,
    session: AsyncSession = Depends(get_session),
):
    """Verify an Apple IAP receipt and activate/update subscription.
    
    Flow:
    1. Send receipt to Apple's verifyReceipt endpoint (try prod first, fallback to sandbox)
    2. Parse latest_receipt_info for active subscription
    3. Update our subscription table
    4. Return entitlement status to client
    """
    receipt_response = await _call_apple_verify(req.receipt_data)

    if not receipt_response:
        raise HTTPException(502, "Failed to verify receipt with Apple")

    status = receipt_response.get("status")
    if status != 0:
        error_messages = {
            21000: "App Store could not read the JSON",
            21002: "Receipt data malformed",
            21003: "Receipt could not be authenticated",
            21004: "Shared secret mismatch",
            21005: "Apple server unavailable — retry",
            21006: "Receipt valid but subscription expired",
            21007: "Sandbox receipt sent to production (auto-retrying)",
            21008: "Production receipt sent to sandbox",
            21010: "Account not found",
        }
        msg = error_messages.get(status, f"Apple verification failed (status {status})")
        if status == 21006:
            # Valid but expired — downgrade to free
            sub = await _get_or_create_subscription(session, req.user_id)
            sub.tier = "free"
            sub.status = "expired"
            sub.updated_at = _now()
            await session.commit()
            return {"tier": "free", "status": "expired", "message": "Subscription expired"}
        raise HTTPException(400, msg)

    # Parse latest receipt info
    latest_info = receipt_response.get("latest_receipt_info", [])
    if not latest_info:
        latest_info = receipt_response.get("receipt", {}).get("in_app", [])

    if not latest_info:
        raise HTTPException(400, "No subscription found in receipt")

    # Find the most recent active subscription
    active_sub = None
    now_ms = int(time.time() * 1000)

    for txn in sorted(latest_info, key=lambda t: int(t.get("expires_date_ms", 0)), reverse=True):
        expires_ms = int(txn.get("expires_date_ms", 0))
        if expires_ms > now_ms:
            active_sub = txn
            break

    if not active_sub:
        # All subscriptions expired
        sub = await _get_or_create_subscription(session, req.user_id)
        sub.tier = "free"
        sub.status = "expired"
        sub.updated_at = _now()
        await session.commit()
        return {"tier": "free", "status": "expired"}

    # Map product ID to tier
    product_id = active_sub.get("product_id", "")
    tier_info = APPLE_PRODUCT_TIER_MAP.get(product_id)
    if not tier_info:
        logger.warning(f"Unknown Apple product ID: {product_id}")
        raise HTTPException(400, f"Unknown product: {product_id}")

    tier, billing = tier_info
    original_txn_id = active_sub.get("original_transaction_id")

    # Update subscription
    sub = await _get_or_create_subscription(session, req.user_id)
    sub.tier = tier.value
    sub.billing_period = billing
    sub.platform = "ios"
    sub.status = "active"
    sub.apple_original_transaction_id = original_txn_id
    sub.current_period_end = _ms_to_dt(active_sub.get("expires_date_ms", 0))
    sub.current_period_start = _ms_to_dt(active_sub.get("purchase_date_ms", 0))
    sub.updated_at = _now()
    if not sub.started_at:
        sub.started_at = _ms_to_dt(active_sub.get("original_purchase_date_ms", 0))

    # Check for trial
    if active_sub.get("is_trial_period") == "true":
        sub.status = "trialing"
        sub.trial_end = sub.current_period_end

    # Log event
    await _log_payment_event(
        session, req.user_id, sub.id,
        "apple_receipt_verified", "apple",
        payload={
            "product_id": product_id,
            "original_transaction_id": original_txn_id,
            "expires_date_ms": active_sub.get("expires_date_ms"),
        },
    )

    await session.commit()

    return {
        "tier": sub.tier,
        "status": sub.status,
        "expires_at": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "is_trial": sub.status == "trialing",
        "product_id": product_id,
    }


async def _call_apple_verify(receipt_data: str) -> dict | None:
    """Call Apple's verifyReceipt — tries production first, falls back to sandbox."""
    payload = {
        "receipt-data": receipt_data,
        "password": APPLE_SHARED_SECRET,
        "exclude-old-transactions": True,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        # Try production first
        try:
            resp = await client.post(APPLE_VERIFY_URL_PROD, json=payload)
            data = resp.json()

            # Status 21007 = sandbox receipt → retry with sandbox URL
            if data.get("status") == 21007:
                resp = await client.post(APPLE_VERIFY_URL_SANDBOX, json=payload)
                data = resp.json()

            return data
        except Exception:
            logger.exception("Apple receipt verification failed")
            return None


# ── Stripe Checkout Session Creation ──────────────────────────────────────────

class CreateCheckoutRequest(BaseModel):
    tier: str  # "pro" | "pro_plus"
    billing_period: str = "monthly"  # "monthly" | "annual"
    success_url: str = "https://fitbites.app/success"
    cancel_url: str = "https://fitbites.app/pricing"


@router.post("/stripe/create-checkout")
async def create_stripe_checkout(
    req: CreateCheckoutRequest,
    user: UserRow = Depends(require_user),
):
    """Create a Stripe Checkout session for web subscription.
    
    Returns a checkout URL for the client to redirect to.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe not configured yet")

    # Look up price ID from our config
    price_key = f"{req.tier}_{req.billing_period}"
    price_id = STRIPE_PRICE_TIER_MAP.get(price_key)

    if not price_id:
        raise HTTPException(400, f"Invalid tier/billing: {req.tier}/{req.billing_period}")

    # Create checkout session via Stripe API
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
            data={
                "mode": "subscription",
                "payment_method_types[]": "card",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "client_reference_id": user.id,
                "customer_email": user.email,
                "success_url": req.success_url + "?session_id={CHECKOUT_SESSION_ID}",
                "cancel_url": req.cancel_url,
                "subscription_data[trial_period_days]": "7",
                "metadata[tier]": req.tier,
                "metadata[billing_period]": req.billing_period,
                "metadata[user_id]": user.id,
            },
        )

    if resp.status_code != 200:
        logger.error(f"Stripe checkout creation failed: {resp.text}")
        raise HTTPException(502, "Failed to create checkout session")

    checkout = resp.json()
    return {
        "checkout_url": checkout.get("url"),
        "session_id": checkout.get("id"),
    }


# ── User Subscription Status ─────────────────────────────────────────────────

@router.get("/me")
async def get_my_subscription(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get current user's subscription status and entitlements."""
    sub = await _get_or_create_subscription(session, user.id)
    await session.commit()

    # Resolve entitlements from pricing engine
    from src.services.pricing import PricingEngine, Tier as PricingTier
    engine = PricingEngine()
    tier_enum = PricingTier(sub.tier) if sub.tier in [t.value for t in PricingTier] else PricingTier.FREE
    tier_config = engine.tiers[tier_enum]

    is_expired = (
        sub.current_period_end is not None
        and sub.current_period_end < _now()
        and sub.status not in ("canceled", "expired")
    )
    if is_expired:
        sub.tier = "free"
        sub.status = "expired"
        sub.updated_at = _now()
        await session.commit()

    return {
        "tier": sub.tier,
        "status": sub.status,
        "platform": sub.platform,
        "billing_period": sub.billing_period,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "is_trial": sub.status == "trialing",
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
        "features": tier_config.features,
        "limits": tier_config.limits,
        "canceled_at": sub.canceled_at.isoformat() if sub.canceled_at else None,
    }
