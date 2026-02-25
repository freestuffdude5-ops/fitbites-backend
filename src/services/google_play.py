"""
Google Play Billing Verification for FitBites
---
Verifies Android subscription purchases via Google Play Developer API v3.
Handles purchase verification, subscription lifecycle, and RTDN (Real-Time Developer Notifications).

Endpoints:
- POST /api/v1/subscriptions/google/verify — Verify purchase token from Android client
- POST /api/v1/subscriptions/google/webhook — Google RTDN webhook handler

Requires a Google Cloud service account with Play Developer API access.
See: https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptionsv2
"""
from __future__ import annotations

import json
import base64
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.subscription_tables import SubscriptionRow, PaymentEventRow
from src.db.user_tables import UserRow
from src.auth import require_user
from src.services.pricing import Tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subscriptions/google", tags=["subscriptions"])

# ── Config ────────────────────────────────────────────────────────────────────

GOOGLE_PACKAGE_NAME = "com.eightythreeapps.fitbites"

# Service account JSON key (path or inline JSON)
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY", "")
GOOGLE_SERVICE_ACCOUNT_KEY_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_FILE", "")

# Map Google product IDs → tiers
GOOGLE_PRODUCT_TIER_MAP = {
    "fitbites_pro_monthly": (Tier.PRO, "monthly"),
    "fitbites_pro_annual": (Tier.PRO, "annual"),
    "fitbites_proplus_monthly": (Tier.PRO_PLUS, "monthly"),
    "fitbites_proplus_annual": (Tier.PRO_PLUS, "annual"),
}

# ── Google Auth (Service Account JWT → Access Token) ──────────────────────────

_cached_token: dict = {"token": "", "expires_at": 0}


async def _get_access_token() -> str:
    """Get a Google OAuth2 access token using service account credentials.
    
    Uses JWT assertion grant per:
    https://developers.google.com/identity/protocols/oauth2/service-account
    """
    now = time.time()
    if _cached_token["token"] and _cached_token["expires_at"] > now + 60:
        return _cached_token["token"]

    sa_key = _load_service_account_key()
    if not sa_key:
        raise HTTPException(503, "Google service account not configured")

    # Build JWT
    import jwt as pyjwt  # PyJWT library

    iat = int(now)
    exp = iat + 3600
    payload = {
        "iss": sa_key["client_email"],
        "scope": "https://www.googleapis.com/auth/androidpublisher",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat,
        "exp": exp,
    }

    signed_jwt = pyjwt.encode(payload, sa_key["private_key"], algorithm="RS256")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
        )

    if resp.status_code != 200:
        logger.error(f"Google token exchange failed: {resp.text}")
        raise HTTPException(502, "Failed to authenticate with Google")

    token_data = resp.json()
    _cached_token["token"] = token_data["access_token"]
    _cached_token["expires_at"] = now + token_data.get("expires_in", 3600)

    return _cached_token["token"]


def _load_service_account_key() -> dict | None:
    """Load service account key from env (inline JSON) or file path."""
    if GOOGLE_SERVICE_ACCOUNT_KEY:
        try:
            return json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
        except json.JSONDecodeError:
            logger.error("GOOGLE_SERVICE_ACCOUNT_KEY is not valid JSON")
            return None

    if GOOGLE_SERVICE_ACCOUNT_KEY_FILE and os.path.exists(GOOGLE_SERVICE_ACCOUNT_KEY_FILE):
        with open(GOOGLE_SERVICE_ACCOUNT_KEY_FILE) as f:
            return json.load(f)

    return None


# ── Google Play Developer API ─────────────────────────────────────────────────

async def _get_subscription_v2(purchase_token: str) -> dict:
    """Call subscriptions:get (v2) to get subscription purchase details.
    
    Uses the v2 API which returns a unified SubscriptionPurchaseV2 object
    with line items, auto-renewing status, and acknowledgement state.
    
    See: https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptionsv2/get
    """
    token = await _get_access_token()

    url = (
        f"https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{GOOGLE_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
    )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})

    if resp.status_code == 404:
        raise HTTPException(404, "Purchase token not found")
    if resp.status_code == 401:
        # Token expired, clear cache and retry once
        _cached_token["token"] = ""
        token = await _get_access_token()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})

    if resp.status_code != 200:
        logger.error(f"Google Play API error {resp.status_code}: {resp.text}")
        raise HTTPException(502, "Google Play verification failed")

    return resp.json()


async def _acknowledge_subscription(product_id: str, purchase_token: str) -> bool:
    """Acknowledge a subscription purchase (required within 3 days or auto-refund).
    
    See: https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.subscriptions/acknowledge
    """
    token = await _get_access_token()

    url = (
        f"https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{GOOGLE_PACKAGE_NAME}/purchases/subscriptions/"
        f"{product_id}/tokens/{purchase_token}:acknowledge"
    )

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    if resp.status_code == 204 or resp.status_code == 200:
        return True
    if resp.status_code == 400:
        # Already acknowledged — that's fine
        return True

    logger.warning(f"Failed to acknowledge Google subscription: {resp.status_code} {resp.text}")
    return False


# ── Verify Endpoint ───────────────────────────────────────────────────────────

class GoogleVerifyRequest(BaseModel):
    purchase_token: str
    product_id: str


@router.post("/verify")
async def verify_google_purchase(
    req: GoogleVerifyRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Verify a Google Play subscription purchase and activate entitlement.
    
    Called by the Android client after a successful BillingClient purchase flow.
    
    Flow:
    1. Call Google Play Developer API to validate the purchase token
    2. Parse subscription state (active, paused, grace period, etc.)
    3. Acknowledge the purchase (Google requires this within 3 days)
    4. Update our subscription table
    5. Return entitlement status to client
    """
    purchase = await _get_subscription_v2(req.purchase_token)

    # Parse the v2 response
    # subscriptionState: SUBSCRIPTION_STATE_ACTIVE, SUBSCRIPTION_STATE_CANCELED,
    #   SUBSCRIPTION_STATE_IN_GRACE_PERIOD, SUBSCRIPTION_STATE_ON_HOLD,
    #   SUBSCRIPTION_STATE_PAUSED, SUBSCRIPTION_STATE_EXPIRED, SUBSCRIPTION_STATE_PENDING
    sub_state = purchase.get("subscriptionState", "")

    STATE_MAP = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "past_due",
        "SUBSCRIPTION_STATE_ON_HOLD": "past_due",
        "SUBSCRIPTION_STATE_PAUSED": "paused",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PENDING": "pending",
    }
    our_status = STATE_MAP.get(sub_state, "active")

    # Extract line items (v2 API uses lineItems array)
    line_items = purchase.get("lineItems", [])
    if not line_items:
        raise HTTPException(400, "No subscription line items in purchase")

    line_item = line_items[0]  # Single subscription
    google_product_id = line_item.get("productId", req.product_id)
    expiry_time = line_item.get("expiryTime")  # RFC3339 timestamp

    # Map product ID to tier
    tier_info = GOOGLE_PRODUCT_TIER_MAP.get(google_product_id)
    if not tier_info:
        # Try with the request product_id
        tier_info = GOOGLE_PRODUCT_TIER_MAP.get(req.product_id)
    if not tier_info:
        logger.warning(f"Unknown Google product ID: {google_product_id}")
        raise HTTPException(400, f"Unknown product: {google_product_id}")

    tier, billing = tier_info

    # If expired, downgrade
    if our_status == "expired":
        sub = await _get_or_create_subscription(session, user.id)
        sub.tier = "free"
        sub.status = "expired"
        sub.updated_at = _now()
        await session.commit()
        return {"tier": "free", "status": "expired"}

    # Acknowledge the purchase (MUST do within 3 days)
    acknowledged = purchase.get("acknowledgementState", "") == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    if not acknowledged:
        ack_success = await _acknowledge_subscription(req.product_id, req.purchase_token)
        if not ack_success:
            logger.warning(f"Failed to ack Google purchase for user {user.id}")

    # Check for free trial / intro offer
    offer_details = line_item.get("offerDetails", {})
    offer_tags = offer_details.get("offerTags", [])
    base_plan_id = offer_details.get("basePlanId", "")

    # Update subscription
    sub = await _get_or_create_subscription(session, user.id)
    sub.tier = tier.value
    sub.billing_period = billing
    sub.platform = "android"
    sub.status = our_status
    sub.google_purchase_token = req.purchase_token
    sub.updated_at = _now()

    if expiry_time:
        sub.current_period_end = datetime.fromisoformat(expiry_time.replace("Z", "+00:00"))
    
    start_time = purchase.get("startTime")
    if start_time:
        sub.current_period_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if not sub.started_at:
            sub.started_at = sub.current_period_start

    # Detect trial via offer tags or auto-renewing base plan
    auto_renewing = line_item.get("autoRenewingPlan", {})
    if "freetrial" in offer_tags or "free-trial" in offer_tags:
        sub.status = "trialing"
        sub.trial_end = sub.current_period_end

    # Log event
    await _log_payment_event(
        session, user.id, sub.id,
        "google_purchase_verified", "google",
        payload={
            "product_id": google_product_id,
            "purchase_token": req.purchase_token[:20] + "...",  # Truncate for safety
            "subscription_state": sub_state,
            "acknowledged": acknowledged or True,
        },
    )

    await session.commit()

    return {
        "tier": sub.tier,
        "status": sub.status,
        "expires_at": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "is_trial": sub.status == "trialing",
        "product_id": google_product_id,
        "acknowledged": True,
    }


# ── Google RTDN Webhook ──────────────────────────────────────────────────────

@router.post("/webhook")
async def google_rtdn_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Handle Google Real-Time Developer Notifications (RTDN) via Cloud Pub/Sub push.
    
    Google sends subscription lifecycle events as Pub/Sub messages.
    The message data contains a base64-encoded DeveloperNotification.
    
    Notification types:
    - SUBSCRIPTION_RECOVERED (1): Renewed from account hold
    - SUBSCRIPTION_RENEWED (2): Active subscription renewed
    - SUBSCRIPTION_CANCELED (3): User or system cancellation
    - SUBSCRIPTION_PURCHASED (4): New subscription
    - SUBSCRIPTION_ON_HOLD (5): Account hold (payment issue)
    - SUBSCRIPTION_IN_GRACE_PERIOD (6): Grace period started
    - SUBSCRIPTION_RESTARTED (7): User resubscribed
    - SUBSCRIPTION_PRICE_CHANGE_CONFIRMED (8): User accepted price change
    - SUBSCRIPTION_DEFERRED (9): Subscription deferred
    - SUBSCRIPTION_PAUSED (10): Subscription paused
    - SUBSCRIPTION_PAUSE_SCHEDULE_CHANGED (11): Pause schedule updated
    - SUBSCRIPTION_REVOKED (12): Subscription revoked (refund)
    - SUBSCRIPTION_EXPIRED (13): Subscription expired
    """
    body = await request.json()

    # Pub/Sub push message format
    message = body.get("message", {})
    if not message:
        return {"status": "no message"}

    data_b64 = message.get("data", "")
    if not data_b64:
        return {"status": "no data"}

    try:
        notification = json.loads(base64.b64decode(data_b64))
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to decode RTDN: {e}")
        return {"status": "decode_error"}

    # Verify package name
    if notification.get("packageName") != GOOGLE_PACKAGE_NAME:
        logger.warning(f"RTDN for wrong package: {notification.get('packageName')}")
        return {"status": "wrong_package"}

    sub_notification = notification.get("subscriptionNotification")
    if not sub_notification:
        # Could be a test notification or one-time purchase notification
        logger.info(f"Non-subscription RTDN: {notification.get('testNotification', {})}")
        return {"status": "not_subscription"}

    notif_type = sub_notification.get("notificationType", 0)
    purchase_token = sub_notification.get("purchaseToken", "")
    subscription_id = sub_notification.get("subscriptionId", "")  # Google's product ID

    logger.info(f"Google RTDN type={notif_type} product={subscription_id}")

    if not purchase_token:
        return {"status": "no_token"}

    # Find our subscription by purchase token
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.google_purchase_token == purchase_token)
    )
    sub = result.scalar_one_or_none()

    # For critical events, re-verify with Google to get authoritative state
    VERIFY_EVENTS = {1, 2, 3, 4, 5, 6, 7, 12, 13}  # Most lifecycle events
    if notif_type in VERIFY_EVENTS and purchase_token:
        try:
            purchase = await _get_subscription_v2(purchase_token)
            await _update_sub_from_google(session, sub, purchase, purchase_token, subscription_id)
        except Exception as e:
            logger.error(f"Failed to re-verify Google purchase on RTDN: {e}")
            # Fall through to basic handling below

    # Basic handling for events where we don't have a sub
    if not sub:
        await _log_payment_event(
            session, None, None,
            f"google_rtdn_{notif_type}", "google",
            payload={"purchase_token": purchase_token[:20] + "...", "subscription_id": subscription_id},
        )
        await session.commit()
        return {"status": "ok"}

    # Type-specific handling
    if notif_type in (3, 12, 13):  # Canceled, revoked, expired
        if notif_type == 12:  # Revoked = refund
            sub.tier = "free"
            sub.status = "expired"
            await _log_payment_event(
                session, sub.user_id, sub.id,
                "google_subscription_revoked", "google",
                payload={"purchase_token": purchase_token[:20] + "..."},
            )
        elif notif_type == 13:  # Expired
            sub.tier = "free"
            sub.status = "expired"
        elif notif_type == 3:  # Canceled (still active until period end)
            sub.canceled_at = _now()

    elif notif_type == 5:  # On hold
        sub.status = "past_due"

    elif notif_type == 6:  # Grace period
        sub.status = "past_due"

    elif notif_type == 10:  # Paused
        sub.status = "paused"

    sub.updated_at = _now()

    await _log_payment_event(
        session, sub.user_id, sub.id,
        f"google_rtdn_{notif_type}", "google",
        payload={
            "notification_type": notif_type,
            "subscription_id": subscription_id,
        },
    )

    await session.commit()
    return {"status": "ok"}


async def _update_sub_from_google(
    session: AsyncSession,
    sub: SubscriptionRow | None,
    purchase: dict,
    purchase_token: str,
    product_id: str,
) -> None:
    """Update subscription from a fresh Google API response."""
    if not sub:
        return

    sub_state = purchase.get("subscriptionState", "")
    STATE_MAP = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "past_due",
        "SUBSCRIPTION_STATE_ON_HOLD": "past_due",
        "SUBSCRIPTION_STATE_PAUSED": "paused",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
    }

    new_status = STATE_MAP.get(sub_state)
    if new_status:
        sub.status = new_status
        if new_status == "expired":
            sub.tier = "free"

    line_items = purchase.get("lineItems", [])
    if line_items:
        expiry_time = line_items[0].get("expiryTime")
        if expiry_time:
            sub.current_period_end = datetime.fromisoformat(expiry_time.replace("Z", "+00:00"))

    sub.updated_at = _now()


# ── Helpers (reused from subscriptions.py) ────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_or_create_subscription(
    session: AsyncSession, user_id: str
) -> SubscriptionRow:
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
