"""Subscription tables — tracks user subscriptions, payments, and receipts."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, DateTime, JSON, Boolean,
    ForeignKey, Index, Text,
)

from src.db.tables import Base


class SubscriptionRow(Base):
    """Active user subscription — single source of truth for entitlements."""
    __tablename__ = "subscriptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)

    # Tier: free | pro | pro_plus
    tier = Column(String(20), nullable=False, default="free")

    # Billing: monthly | annual
    billing_period = Column(String(20), nullable=True)

    # Platform: web (Stripe) | ios (Apple IAP) | android (Google Play)
    platform = Column(String(20), nullable=True)

    # Status: active | canceled | past_due | expired | trialing
    status = Column(String(20), nullable=False, default="active")

    # External IDs
    stripe_subscription_id = Column(String(255), nullable=True, unique=True, index=True)
    stripe_customer_id = Column(String(255), nullable=True, index=True)
    apple_original_transaction_id = Column(String(255), nullable=True, unique=True, index=True)
    google_purchase_token = Column(String(500), nullable=True, unique=True, index=True)

    # Dates
    started_at = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)

    # A/B test tracking
    experiment_id = Column(String(100), nullable=True)
    variant_id = Column(String(50), nullable=True)
    price_paid = Column(Float, nullable=True)  # Actual price (for A/B analysis)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow())


class PaymentEventRow(Base):
    """Immutable log of all payment events (webhooks, receipts, refunds)."""
    __tablename__ = "payment_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    subscription_id = Column(String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)

    # Event type: subscription.created | subscription.updated | invoice.paid | charge.refunded | apple_receipt_verified
    event_type = Column(String(100), nullable=False, index=True)

    # Source: stripe | apple | google
    source = Column(String(20), nullable=False)

    # Raw event payload (for debugging / reconciliation)
    payload = Column(JSON, nullable=True)

    # Amount in cents
    amount_cents = Column(Float, nullable=True)
    currency = Column(String(3), default="USD")

    created_at = Column(DateTime, default=lambda: datetime.utcnow(), index=True)

    __table_args__ = (
        Index("ix_payment_events_source_type", "source", "event_type"),
    )
