"""Tests for subscription management — Stripe webhooks, Apple IAP, entitlements."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.services.subscriptions import (
    _verify_stripe_signature,
    _now,
    _ms_to_dt,
    APPLE_PRODUCT_TIER_MAP,
)
from src.services.pricing import Tier


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stripe_signature(payload: bytes, secret: str = "whsec_test") -> str:
    """Generate a valid Stripe webhook signature."""
    timestamp = str(int(time.time()))
    signed = f"{timestamp}.{payload.decode()}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def _stripe_event(event_type: str, data: dict) -> dict:
    return {"type": event_type, "data": {"object": data}}


# ── Stripe Signature Verification ────────────────────────────────────────────

class TestStripeSignature:
    def test_valid_signature(self):
        secret = "whsec_test123"
        payload = b'{"type": "test"}'
        sig = _make_stripe_signature(payload, secret)
        result = _verify_stripe_signature(payload, sig, secret)
        assert result["type"] == "test"

    def test_invalid_signature_rejects(self):
        with pytest.raises(Exception):
            _verify_stripe_signature(b'{"type":"test"}', "t=123,v1=bad", "whsec_test")

    def test_missing_secret_raises(self):
        with pytest.raises(Exception):
            _verify_stripe_signature(b'{}', "t=1,v1=abc", "")

    def test_old_timestamp_rejects(self):
        secret = "whsec_test"
        payload = b'{"type": "test"}'
        old_ts = str(int(time.time()) - 600)  # 10 min ago
        signed = f"{old_ts}.{payload.decode()}"
        sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        header = f"t={old_ts},v1={sig}"
        with pytest.raises(Exception):
            _verify_stripe_signature(payload, header, secret)


# ── Helper Functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_ms_to_dt(self):
        dt = _ms_to_dt(1700000000000)
        assert dt.year == 2023
        assert dt.tzinfo is not None

    def test_now_has_timezone(self):
        now = _now()
        assert now.tzinfo is not None

    def test_apple_product_map_has_all_tiers(self):
        tiers_found = set()
        for product_id, (tier, billing) in APPLE_PRODUCT_TIER_MAP.items():
            tiers_found.add(tier)
            assert billing in ("monthly", "annual")
            assert "com.83apps.fitbites" in product_id
        assert Tier.PRO in tiers_found
        assert Tier.PRO_PLUS in tiers_found


# ── API Integration Tests ─────────────────────────────────────────────────────

@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestSubscriptionEndpoints:
    @pytest.mark.asyncio
    async def test_get_subscription_requires_auth(self, client):
        resp = await client.get("/api/v1/subscriptions/me")
        assert resp.status_code == 401 or resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stripe_webhook_rejects_no_signature(self, client):
        resp = await client.post(
            "/api/v1/subscriptions/stripe/webhook",
            content=b'{"type":"test"}',
        )
        # Should fail due to missing stripe-signature header
        assert resp.status_code == 422 or resp.status_code == 400

    @pytest.mark.asyncio
    async def test_apple_verify_requires_body(self, client):
        resp = await client.post("/api/v1/subscriptions/apple/verify", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_apple_verify_requires_receipt_data(self, client):
        resp = await client.post(
            "/api/v1/subscriptions/apple/verify",
            json={"user_id": "test-user"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_checkout_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/subscriptions/stripe/create-checkout",
            json={"tier": "pro"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    @patch("src.services.subscriptions.STRIPE_WEBHOOK_SECRET", "whsec_test")
    async def test_stripe_webhook_invalid_sig(self, client):
        resp = await client.post(
            "/api/v1/subscriptions/stripe/webhook",
            content=b'{"type":"test"}',
            headers={"stripe-signature": "t=0,v1=invalid"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.services.subscriptions._call_apple_verify")
    async def test_apple_verify_expired_receipt(self, mock_verify, client):
        mock_verify.return_value = {"status": 21006}
        resp = await client.post(
            "/api/v1/subscriptions/apple/verify",
            json={"receipt_data": "base64data", "user_id": "test-user-expired"},
        )
        # Should handle gracefully (either downgrade or error)
        assert resp.status_code in (200, 400)

    @pytest.mark.asyncio
    @patch("src.services.subscriptions._call_apple_verify")
    async def test_apple_verify_malformed_receipt(self, mock_verify, client):
        mock_verify.return_value = {"status": 21002}
        resp = await client.post(
            "/api/v1/subscriptions/apple/verify",
            json={"receipt_data": "bad", "user_id": "test-user"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.services.subscriptions._call_apple_verify")
    async def test_apple_verify_server_down(self, mock_verify, client):
        mock_verify.return_value = None
        resp = await client.post(
            "/api/v1/subscriptions/apple/verify",
            json={"receipt_data": "data", "user_id": "test-user"},
        )
        assert resp.status_code == 502


# ── Stripe Webhook Event Handling ─────────────────────────────────────────────

class TestStripeEvents:
    @pytest.mark.asyncio
    @patch("src.services.subscriptions.STRIPE_WEBHOOK_SECRET", "whsec_test")
    async def test_checkout_completed_creates_subscription(self, client):
        event = _stripe_event("checkout.session.completed", {
            "client_reference_id": "user-123",
            "subscription": "sub_abc",
            "customer": "cus_xyz",
            "amount_total": 499,
            "metadata": {"tier": "pro", "billing_period": "monthly"},
        })
        payload = json.dumps(event).encode()
        sig = _make_stripe_signature(payload, "whsec_test")

        resp = await client.post(
            "/api/v1/subscriptions/stripe/webhook",
            content=payload,
            headers={"stripe-signature": sig},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    @patch("src.services.subscriptions.STRIPE_WEBHOOK_SECRET", "whsec_test")
    async def test_unhandled_event_type_ok(self, client):
        event = _stripe_event("some.unknown.event", {})
        payload = json.dumps(event).encode()
        sig = _make_stripe_signature(payload, "whsec_test")

        resp = await client.post(
            "/api/v1/subscriptions/stripe/webhook",
            content=payload,
            headers={"stripe-signature": sig},
        )
        assert resp.status_code == 200
