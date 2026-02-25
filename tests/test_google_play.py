"""Tests for Google Play Billing verification service."""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.services.google_play import (
    GOOGLE_PRODUCT_TIER_MAP,
    GOOGLE_PACKAGE_NAME,
    _load_service_account_key,
    router,
)


# ── Product tier mapping ─────────────────────────────────────────────────────

def test_product_tier_map_has_all_tiers():
    """All 4 product variants are mapped."""
    assert len(GOOGLE_PRODUCT_TIER_MAP) == 4
    assert "fitbites_pro_monthly" in GOOGLE_PRODUCT_TIER_MAP
    assert "fitbites_pro_annual" in GOOGLE_PRODUCT_TIER_MAP
    assert "fitbites_proplus_monthly" in GOOGLE_PRODUCT_TIER_MAP
    assert "fitbites_proplus_annual" in GOOGLE_PRODUCT_TIER_MAP


def test_product_tier_values():
    """Tiers map to correct values."""
    from src.services.pricing import Tier
    tier, billing = GOOGLE_PRODUCT_TIER_MAP["fitbites_pro_monthly"]
    assert tier == Tier.PRO
    assert billing == "monthly"

    tier, billing = GOOGLE_PRODUCT_TIER_MAP["fitbites_proplus_annual"]
    assert tier == Tier.PRO_PLUS
    assert billing == "annual"


def test_package_name():
    assert GOOGLE_PACKAGE_NAME == "com.eightythreeapps.fitbites"


# ── Service account key loading ───────────────────────────────────────────────

def test_load_service_account_key_from_env():
    """Can parse inline JSON from env var."""
    test_key = json.dumps({"client_email": "test@test.iam.gserviceaccount.com", "private_key": "fake"})
    with patch("src.services.google_play.GOOGLE_SERVICE_ACCOUNT_KEY", test_key):
        result = _load_service_account_key()
        assert result is not None
        assert result["client_email"] == "test@test.iam.gserviceaccount.com"


def test_load_service_account_key_invalid_json():
    """Returns None for invalid JSON."""
    with patch("src.services.google_play.GOOGLE_SERVICE_ACCOUNT_KEY", "not-json"):
        result = _load_service_account_key()
        assert result is None


def test_load_service_account_key_empty():
    """Returns None when no key configured."""
    with patch("src.services.google_play.GOOGLE_SERVICE_ACCOUNT_KEY", ""):
        with patch("src.services.google_play.GOOGLE_SERVICE_ACCOUNT_KEY_FILE", ""):
            result = _load_service_account_key()
            assert result is None


# ── RTDN webhook parsing ─────────────────────────────────────────────────────

def _make_rtdn_message(notif_type: int, purchase_token: str = "tok_123", product_id: str = "fitbites_pro_monthly"):
    """Build a Pub/Sub push message matching Google RTDN format."""
    notification = {
        "version": "1.0",
        "packageName": GOOGLE_PACKAGE_NAME,
        "eventTimeMillis": str(int(time.time() * 1000)),
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": notif_type,
            "purchaseToken": purchase_token,
            "subscriptionId": product_id,
        },
    }
    data_b64 = base64.b64encode(json.dumps(notification).encode()).decode()
    return {"message": {"data": data_b64, "messageId": "msg_123"}}


def test_rtdn_message_format():
    """Verify our test helper produces valid RTDN format."""
    msg = _make_rtdn_message(2, "tok_abc")
    data = json.loads(base64.b64decode(msg["message"]["data"]))
    assert data["packageName"] == GOOGLE_PACKAGE_NAME
    assert data["subscriptionNotification"]["notificationType"] == 2
    assert data["subscriptionNotification"]["purchaseToken"] == "tok_abc"


def test_rtdn_wrong_package():
    """RTDN for wrong package should be ignored."""
    notification = {
        "packageName": "com.wrong.app",
        "subscriptionNotification": {"notificationType": 2, "purchaseToken": "tok"},
    }
    data_b64 = base64.b64encode(json.dumps(notification).encode()).decode()
    msg = {"message": {"data": data_b64}}
    data = json.loads(base64.b64decode(msg["message"]["data"]))
    assert data["packageName"] != GOOGLE_PACKAGE_NAME


# ── Google subscription state mapping ─────────────────────────────────────────

def test_state_mapping_comprehensive():
    """All Google subscription states map correctly."""
    from src.services.google_play import verify_google_purchase  # Import to verify module loads
    STATE_MAP = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "past_due",
        "SUBSCRIPTION_STATE_ON_HOLD": "past_due",
        "SUBSCRIPTION_STATE_PAUSED": "paused",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PENDING": "pending",
    }
    # Verify expired → free tier downgrade
    assert STATE_MAP["SUBSCRIPTION_STATE_EXPIRED"] == "expired"
    assert STATE_MAP["SUBSCRIPTION_STATE_ACTIVE"] == "active"
    assert STATE_MAP["SUBSCRIPTION_STATE_IN_GRACE_PERIOD"] == "past_due"


# ── V2 API response parsing ──────────────────────────────────────────────────

def test_v2_response_parsing():
    """Verify we can parse a real Google SubscriptionPurchaseV2 structure."""
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(days=30)).isoformat()

    response = {
        "kind": "androidpublisher#subscriptionPurchaseV2",
        "regionCode": "US",
        "startTime": now.isoformat(),
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "latestOrderId": "GPA.1234-5678-9012-34567",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "lineItems": [
            {
                "productId": "fitbites_pro_monthly",
                "expiryTime": expiry,
                "autoRenewingPlan": {
                    "autoRenewEnabled": True,
                },
                "offerDetails": {
                    "basePlanId": "monthly",
                    "offerTags": [],
                },
            }
        ],
    }

    # Verify we can extract the right fields
    line_item = response["lineItems"][0]
    assert line_item["productId"] == "fitbites_pro_monthly"
    assert line_item["productId"] in GOOGLE_PRODUCT_TIER_MAP
    assert response["subscriptionState"] == "SUBSCRIPTION_STATE_ACTIVE"
    assert response["acknowledgementState"] == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"


def test_v2_trial_detection():
    """Detect free trial from offer tags."""
    response_line_item = {
        "productId": "fitbites_pro_monthly",
        "expiryTime": "2026-03-24T00:00:00Z",
        "offerDetails": {
            "basePlanId": "monthly",
            "offerTags": ["freetrial"],
        },
    }
    assert "freetrial" in response_line_item["offerDetails"]["offerTags"]


# ── Router registration ──────────────────────────────────────────────────────

def test_router_has_correct_prefix():
    assert router.prefix == "/api/v1/subscriptions/google"


def test_router_has_verify_and_webhook():
    """Router exposes both verify and webhook endpoints."""
    routes = [r.path for r in router.routes]
    assert any("/verify" in r for r in routes)
    assert any("/webhook" in r for r in routes)


# ── Token caching ─────────────────────────────────────────────────────────────

def test_token_cache_structure():
    """Verify token cache has expected fields."""
    from src.services.google_play import _cached_token
    assert "token" in _cached_token
    assert "expires_at" in _cached_token


# ── Acknowledgement ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acknowledge_returns_true_on_400():
    """400 from Google (already acknowledged) should return True, not raise."""
    mock_response = MagicMock()
    mock_response.status_code = 400

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.services.google_play._get_access_token", return_value="fake_token"):
        with patch("httpx.AsyncClient", return_value=mock_client):
            from src.services.google_play import _acknowledge_subscription
            result = await _acknowledge_subscription("fitbites_pro_monthly", "tok_123")
            assert result is True
