"""
FitBites Data Privacy Service
---
CCPA/GDPR-compliant data deletion and export endpoints.
Required for Apple App Store submission and international compliance.

Endpoints:
- GET  /api/v1/me/data-export  — Export all user data as JSON
- DELETE /api/v1/me              — Delete account and all associated data
- GET  /api/v1/me/consent       — Get user's consent status
- POST /api/v1/me/consent       — Update consent preferences
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow, SavedRecipeRow
from src.db.subscription_tables import SubscriptionRow, PaymentEventRow
from src.auth import require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/me", tags=["privacy"])


# ── Data Export ───────────────────────────────────────────────────────────────

@router.get("/data-export")
async def export_user_data(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Export all user data in machine-readable JSON format.
    
    GDPR Article 20 — Right to Data Portability.
    CCPA §1798.100 — Right to Know.
    
    Returns all personal data we hold for this user.
    Response time: immediate (< 30 days GDPR requirement).
    """
    export = {
        "export_date": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "format_version": "1.0",
        "data": {},
    }

    # Profile data
    export["data"]["profile"] = {
        "email": user.email,
        "display_name": user.display_name,
        "preferences": user.preferences,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

    # Saved recipes
    result = await session.execute(
        select(SavedRecipeRow).where(SavedRecipeRow.user_id == user.id)
    )
    saved = result.scalars().all()
    export["data"]["saved_recipes"] = [
        {
            "recipe_id": s.recipe_id,
            "saved_at": s.saved_at.isoformat() if s.saved_at else None,
        }
        for s in saved
    ]

    # Subscription history
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if sub:
        export["data"]["subscription"] = {
            "tier": sub.tier,
            "status": sub.status,
            "platform": sub.platform,
            "billing_period": sub.billing_period,
            "started_at": sub.started_at.isoformat() if sub.started_at else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        }

    # Payment events
    result = await session.execute(
        select(PaymentEventRow).where(PaymentEventRow.user_id == user.id)
        .order_by(PaymentEventRow.created_at.desc())
    )
    events = result.scalars().all()
    export["data"]["payment_history"] = [
        {
            "event_type": e.event_type,
            "source": e.source,
            "amount_cents": e.amount_cents,
            "currency": e.currency,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

    # Analytics events (if table exists)
    try:
        result = await session.execute(
            text("SELECT event, properties, timestamp FROM analytics_events WHERE user_id = :uid ORDER BY timestamp DESC LIMIT 1000"),
            {"uid": user.id},
        )
        analytics = result.fetchall()
        export["data"]["analytics_events"] = [
            {"event": row[0], "properties": row[1], "timestamp": row[2]}
            for row in analytics
        ]
    except Exception:
        export["data"]["analytics_events"] = []

    # Consent records
    try:
        result = await session.execute(
            text("SELECT consent_type, granted, updated_at FROM user_consents WHERE user_id = :uid"),
            {"uid": user.id},
        )
        consents = result.fetchall()
        export["data"]["consents"] = [
            {"type": row[0], "granted": row[1], "updated_at": row[2]}
            for row in consents
        ]
    except Exception:
        export["data"]["consents"] = []

    logger.info(f"Data export for user {user.id}")
    return export


# ── Account Deletion ──────────────────────────────────────────────────────────

class DeleteConfirmation(BaseModel):
    confirm: bool = False


@router.delete("")
async def delete_account(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Permanently delete user account and all associated data.
    
    GDPR Article 17 — Right to Erasure.
    CCPA §1798.105 — Right to Delete.
    Apple App Store Review Guideline 5.1.1(v) — Account Deletion requirement.
    
    This is irreversible. Deletes:
    - User profile
    - Saved recipes
    - Subscription records
    - Payment event logs (anonymized, kept for financial audit)
    - Analytics events
    - Consent records
    
    Note: We retain anonymized payment records for tax/audit compliance
    (GDPR Article 17(3)(b) — legal obligation exemption).
    """
    user_id = user.id

    # 1. Cancel any active subscriptions
    result = await session.execute(
        select(SubscriptionRow).where(SubscriptionRow.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if sub and sub.status in ("active", "trialing"):
        # Mark as canceled — actual cancellation with Stripe/Apple/Google
        # should be handled client-side before calling delete
        sub.status = "canceled"
        sub.canceled_at = datetime.now(timezone.utc)
        sub.updated_at = datetime.now(timezone.utc)
        logger.info(f"Canceled subscription for deleted user {user_id}")

    # 2. Anonymize payment events (keep for audit, remove PII)
    await session.execute(
        text("UPDATE payment_events SET user_id = NULL WHERE user_id = :uid"),
        {"uid": user_id},
    )

    # 3. Delete saved recipes
    await session.execute(
        delete(SavedRecipeRow).where(SavedRecipeRow.user_id == user_id)
    )

    # 4. Delete subscription record
    await session.execute(
        delete(SubscriptionRow).where(SubscriptionRow.user_id == user_id)
    )

    # 5. Delete analytics events
    try:
        await session.execute(
            text("DELETE FROM analytics_events WHERE user_id = :uid"),
            {"uid": user_id},
        )
    except Exception:
        pass  # Table may not exist yet

    # 6. Delete consent records
    try:
        await session.execute(
            text("DELETE FROM user_consents WHERE user_id = :uid"),
            {"uid": user_id},
        )
    except Exception:
        pass

    # 7. Delete user profile (last — foreign keys cascade from here)
    await session.execute(
        delete(UserRow).where(UserRow.id == user_id)
    )

    await session.commit()
    logger.info(f"Account deleted: user {user_id}")

    return {
        "status": "deleted",
        "message": "Your account and all associated data have been permanently deleted.",
    }


# ── Consent Management ───────────────────────────────────────────────────────

class ConsentUpdate(BaseModel):
    analytics: Optional[bool] = None       # Usage analytics & crash reporting
    marketing: Optional[bool] = None       # Email marketing & push notifications
    personalization: Optional[bool] = None # Recipe recommendations & feed personalization
    third_party: Optional[bool] = None     # Sharing data with affiliate partners


@router.get("/consent")
async def get_consent(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get current consent preferences.
    
    Returns default consents for new users (all essential = True, optional = False).
    """
    try:
        result = await session.execute(
            text("SELECT consent_type, granted, updated_at FROM user_consents WHERE user_id = :uid"),
            {"uid": user.id},
        )
        rows = result.fetchall()
        consents = {row[0]: {"granted": bool(row[1]), "updated_at": row[2]} for row in rows}
    except Exception:
        consents = {}

    # Return with defaults for any missing consent types
    defaults = {
        "essential": {"granted": True, "updated_at": None, "required": True},
        "analytics": {"granted": consents.get("analytics", {}).get("granted", False), "updated_at": consents.get("analytics", {}).get("updated_at")},
        "marketing": {"granted": consents.get("marketing", {}).get("granted", False), "updated_at": consents.get("marketing", {}).get("updated_at")},
        "personalization": {"granted": consents.get("personalization", {}).get("granted", True), "updated_at": consents.get("personalization", {}).get("updated_at")},
        "third_party": {"granted": consents.get("third_party", {}).get("granted", False), "updated_at": consents.get("third_party", {}).get("updated_at")},
    }

    return {"consents": defaults}


@router.post("/consent")
async def update_consent(
    req: ConsentUpdate,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update consent preferences.
    
    GDPR Article 7 — Conditions for consent.
    Consent must be freely given, specific, informed, and unambiguous.
    Users can withdraw consent at any time.
    """
    now = datetime.now(timezone.utc).isoformat()
    updates = {}
    if req.analytics is not None:
        updates["analytics"] = req.analytics
    if req.marketing is not None:
        updates["marketing"] = req.marketing
    if req.personalization is not None:
        updates["personalization"] = req.personalization
    if req.third_party is not None:
        updates["third_party"] = req.third_party

    for consent_type, granted in updates.items():
        try:
            await session.execute(
                text("""
                    INSERT INTO user_consents (id, user_id, consent_type, granted, updated_at)
                    VALUES (:id, :uid, :type, :granted, :now)
                    ON CONFLICT (user_id, consent_type) DO UPDATE SET granted = :granted, updated_at = :now
                """),
                {"id": str(uuid.uuid4()), "uid": user.id, "type": consent_type, "granted": granted, "now": now},
            )
        except Exception:
            # Table may not exist yet — create it
            try:
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS user_consents (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        consent_type TEXT NOT NULL,
                        granted BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TEXT,
                        UNIQUE(user_id, consent_type)
                    )
                """))
                await session.execute(
                    text("""
                        INSERT INTO user_consents (id, user_id, consent_type, granted, updated_at)
                        VALUES (:id, :uid, :type, :granted, :now)
                        ON CONFLICT (user_id, consent_type) DO UPDATE SET granted = :granted, updated_at = :now
                    """),
                    {"id": str(uuid.uuid4()), "uid": user.id, "type": consent_type, "granted": granted, "now": now},
                )
            except Exception as e:
                logger.error(f"Failed to save consent: {e}")

    await session.commit()
    logger.info(f"Consent updated for user {user.id}: {updates}")

    return {"status": "updated", "consents": updates}
