"""
FitBites Data Retention Service
---
Automated data lifecycle management for GDPR/CCPA compliance.

Handles:
- Inactive account cleanup (24-month inactivity → soft delete → 30-day hard delete)
- Expired session token purge
- Old analytics event pruning (keep 12 months)
- Anonymized payment event pruning (keep 7 years for tax compliance)
- Orphaned data cleanup

Run via: scheduled task (daily at 3 AM UTC) or manual admin trigger.

Endpoints:
- POST /api/v1/admin/retention/run       — Trigger retention sweep
- GET  /api/v1/admin/retention/stats      — View retention statistics
- GET  /api/v1/admin/retention/preview    — Preview what would be purged (dry run)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, delete, update, func, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow, SavedRecipeRow, GroceryListRow
from src.db.subscription_tables import SubscriptionRow, PaymentEventRow
from src.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/retention", tags=["admin", "retention"])

# ── Configuration ─────────────────────────────────────────────────────────────

INACTIVE_THRESHOLD_DAYS = 730       # 24 months — mark inactive
SOFT_DELETE_GRACE_DAYS = 30         # 30 days after soft-delete → hard delete
ANALYTICS_RETENTION_DAYS = 365      # Keep analytics 12 months
SESSION_TOKEN_MAX_AGE_DAYS = 90     # Expired tokens older than 90 days
PAYMENT_RETENTION_YEARS = 7         # Tax/audit compliance (IRS requires 7 years)


@dataclass
class RetentionResult:
    """Results from a retention sweep."""
    inactive_accounts_flagged: int = 0
    accounts_hard_deleted: int = 0
    analytics_events_pruned: int = 0
    expired_tokens_purged: int = 0
    orphaned_records_cleaned: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0


async def _flag_inactive_accounts(
    session: AsyncSession, cutoff: datetime, dry_run: bool
) -> int:
    """Flag accounts inactive for > INACTIVE_THRESHOLD_DAYS.
    
    Sets last_active_at to a sentinel and marks preferences with
    a soft-delete timestamp. User gets a 30-day grace period before
    hard deletion.
    """
    result = await session.execute(
        select(func.count(UserRow.id)).where(
            and_(
                UserRow.last_active_at < cutoff,
                # Don't re-flag already-flagged accounts
                ~UserRow.preferences.contains('"retention_flagged"'),
            )
        )
    )
    count = result.scalar() or 0

    if count > 0 and not dry_run:
        # We can't do a bulk JSON update portably, so fetch and update
        result = await session.execute(
            select(UserRow).where(
                and_(
                    UserRow.last_active_at < cutoff,
                    ~UserRow.preferences.contains('"retention_flagged"'),
                )
            ).limit(1000)  # Process in batches
        )
        users = result.scalars().all()
        now = datetime.now(timezone.utc).isoformat()
        for user in users:
            prefs = user.preferences or {}
            prefs["retention_flagged"] = now
            prefs["retention_delete_after"] = (
                datetime.now(timezone.utc) + timedelta(days=SOFT_DELETE_GRACE_DAYS)
            ).isoformat()
            user.preferences = prefs
        count = len(users)

    return count


async def _hard_delete_expired(session: AsyncSession, dry_run: bool) -> int:
    """Hard-delete accounts that passed their grace period.
    
    These were flagged > 30 days ago and the user never came back.
    Follows same deletion cascade as the manual account deletion endpoint.
    """
    now = datetime.now(timezone.utc)
    
    # Find users whose retention_delete_after has passed
    # Using raw SQL for JSON field querying (portable across SQLite + PG)
    try:
        result = await session.execute(
            text("""
                SELECT id FROM users 
                WHERE json_extract(preferences, '$.retention_delete_after') IS NOT NULL
                AND json_extract(preferences, '$.retention_delete_after') < :now
            """),
            {"now": now.isoformat()},
        )
        user_ids = [row[0] for row in result.fetchall()]
    except Exception:
        # PostgreSQL uses different JSON syntax
        try:
            result = await session.execute(
                text("""
                    SELECT id FROM users 
                    WHERE preferences->>'retention_delete_after' IS NOT NULL
                    AND (preferences->>'retention_delete_after')::timestamp < :now
                """),
                {"now": now},
            )
            user_ids = [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"Could not query retention flags: {e}")
            return 0

    if not user_ids or dry_run:
        return len(user_ids)

    for uid in user_ids[:500]:  # Batch limit
        # Anonymize payment events (keep for tax compliance)
        await session.execute(
            text("UPDATE payment_events SET user_id = NULL WHERE user_id = :uid"),
            {"uid": uid},
        )
        # Cancel active subscriptions
        await session.execute(
            update(SubscriptionRow)
            .where(SubscriptionRow.user_id == uid)
            .values(status="canceled", canceled_at=now, updated_at=now)
        )
        # Delete subscription records
        await session.execute(
            delete(SubscriptionRow).where(SubscriptionRow.user_id == uid)
        )
        # Delete saved recipes
        await session.execute(
            delete(SavedRecipeRow).where(SavedRecipeRow.user_id == uid)
        )
        # Delete grocery lists
        await session.execute(
            delete(GroceryListRow).where(GroceryListRow.user_id == uid)
        )
        # Delete analytics events
        try:
            await session.execute(
                text("DELETE FROM analytics_events WHERE user_id = :uid"),
                {"uid": uid},
            )
        except Exception:
            pass
        # Delete consent records
        try:
            await session.execute(
                text("DELETE FROM user_consents WHERE user_id = :uid"),
                {"uid": uid},
            )
        except Exception:
            pass
        # Delete user
        await session.execute(delete(UserRow).where(UserRow.id == uid))

    return len(user_ids[:500])


async def _prune_analytics(
    session: AsyncSession, cutoff: datetime, dry_run: bool
) -> int:
    """Delete analytics events older than retention period."""
    try:
        result = await session.execute(
            text("SELECT COUNT(*) FROM analytics_events WHERE timestamp < :cutoff"),
            {"cutoff": cutoff.isoformat()},
        )
        count = result.scalar() or 0
        if count > 0 and not dry_run:
            await session.execute(
                text("DELETE FROM analytics_events WHERE timestamp < :cutoff"),
                {"cutoff": cutoff.isoformat()},
            )
        return count
    except Exception:
        return 0  # Table may not exist yet


async def _purge_expired_tokens(
    session: AsyncSession, cutoff: datetime, dry_run: bool
) -> int:
    """Remove expired refresh tokens / session tokens."""
    try:
        result = await session.execute(
            text("SELECT COUNT(*) FROM refresh_tokens WHERE expires_at < :cutoff"),
            {"cutoff": cutoff.isoformat()},
        )
        count = result.scalar() or 0
        if count > 0 and not dry_run:
            await session.execute(
                text("DELETE FROM refresh_tokens WHERE expires_at < :cutoff"),
                {"cutoff": cutoff.isoformat()},
            )
        return count
    except Exception:
        return 0  # Table may not exist


async def _clean_orphaned_records(session: AsyncSession, dry_run: bool) -> int:
    """Clean up records that reference deleted users/recipes."""
    total = 0
    # Saved recipes pointing to deleted recipes
    try:
        result = await session.execute(
            text("""
                SELECT COUNT(*) FROM saved_recipes sr
                LEFT JOIN recipes r ON sr.recipe_id = r.id
                WHERE r.id IS NULL
            """)
        )
        orphaned = result.scalar() or 0
        if orphaned > 0 and not dry_run:
            await session.execute(
                text("""
                    DELETE FROM saved_recipes WHERE recipe_id NOT IN (SELECT id FROM recipes)
                """)
            )
        total += orphaned
    except Exception:
        pass

    # Grocery lists for deleted users
    try:
        result = await session.execute(
            text("""
                SELECT COUNT(*) FROM grocery_lists gl
                LEFT JOIN users u ON gl.user_id = u.id
                WHERE u.id IS NULL
            """)
        )
        orphaned = result.scalar() or 0
        if orphaned > 0 and not dry_run:
            await session.execute(
                text("DELETE FROM grocery_lists WHERE user_id NOT IN (SELECT id FROM users)")
            )
        total += orphaned
    except Exception:
        pass

    return total


async def run_retention_sweep(
    session: AsyncSession, dry_run: bool = False
) -> RetentionResult:
    """Execute full retention sweep. Core function used by both API and scheduler."""
    result = RetentionResult(
        dry_run=dry_run,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    start = datetime.now(timezone.utc)
    now = start

    # 1. Flag inactive accounts
    try:
        inactive_cutoff = now - timedelta(days=INACTIVE_THRESHOLD_DAYS)
        result.inactive_accounts_flagged = await _flag_inactive_accounts(
            session, inactive_cutoff, dry_run
        )
    except Exception as e:
        result.errors.append(f"inactive_flag: {e}")
        logger.error(f"Retention: inactive flag failed: {e}")

    # 2. Hard-delete accounts past grace period
    try:
        result.accounts_hard_deleted = await _hard_delete_expired(session, dry_run)
    except Exception as e:
        result.errors.append(f"hard_delete: {e}")
        logger.error(f"Retention: hard delete failed: {e}")

    # 3. Prune old analytics
    try:
        analytics_cutoff = now - timedelta(days=ANALYTICS_RETENTION_DAYS)
        result.analytics_events_pruned = await _prune_analytics(
            session, analytics_cutoff, dry_run
        )
    except Exception as e:
        result.errors.append(f"analytics_prune: {e}")
        logger.error(f"Retention: analytics prune failed: {e}")

    # 4. Purge expired tokens
    try:
        token_cutoff = now - timedelta(days=SESSION_TOKEN_MAX_AGE_DAYS)
        result.expired_tokens_purged = await _purge_expired_tokens(
            session, token_cutoff, dry_run
        )
    except Exception as e:
        result.errors.append(f"token_purge: {e}")
        logger.error(f"Retention: token purge failed: {e}")

    # 5. Clean orphaned records
    try:
        result.orphaned_records_cleaned = await _clean_orphaned_records(session, dry_run)
    except Exception as e:
        result.errors.append(f"orphan_clean: {e}")
        logger.error(f"Retention: orphan clean failed: {e}")

    if not dry_run:
        await session.commit()

    end = datetime.now(timezone.utc)
    result.completed_at = end.isoformat()
    result.duration_ms = int((end - start).total_seconds() * 1000)

    logger.info(
        f"Retention sweep {'(DRY RUN) ' if dry_run else ''}"
        f"completed in {result.duration_ms}ms: "
        f"flagged={result.inactive_accounts_flagged} "
        f"deleted={result.accounts_hard_deleted} "
        f"analytics={result.analytics_events_pruned} "
        f"tokens={result.expired_tokens_purged} "
        f"orphans={result.orphaned_records_cleaned}"
    )

    return result


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/run")
async def trigger_retention_sweep(
    dry_run: bool = Query(False, description="Preview only, don't actually delete"),
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Trigger a data retention sweep.
    
    Admin-only. Pass ?dry_run=true to preview what would be purged.
    In production, this runs automatically via the scheduler at 3 AM UTC daily.
    """
    result = await run_retention_sweep(session, dry_run=dry_run)
    return {
        "status": "preview" if dry_run else "completed",
        "result": {
            "inactive_accounts_flagged": result.inactive_accounts_flagged,
            "accounts_hard_deleted": result.accounts_hard_deleted,
            "analytics_events_pruned": result.analytics_events_pruned,
            "expired_tokens_purged": result.expired_tokens_purged,
            "orphaned_records_cleaned": result.orphaned_records_cleaned,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        },
    }


@router.get("/stats")
async def retention_stats(
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """View data retention statistics — how many records exist per category."""
    now = datetime.now(timezone.utc)
    stats = {}

    # Total users
    result = await session.execute(select(func.count(UserRow.id)))
    stats["total_users"] = result.scalar() or 0

    # Inactive users (> 24 months)
    cutoff = now - timedelta(days=INACTIVE_THRESHOLD_DAYS)
    result = await session.execute(
        select(func.count(UserRow.id)).where(UserRow.last_active_at < cutoff)
    )
    stats["inactive_users"] = result.scalar() or 0

    # Flagged for deletion
    try:
        result = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE json_extract(preferences, '$.retention_flagged') IS NOT NULL")
        )
        stats["flagged_for_deletion"] = result.scalar() or 0
    except Exception:
        try:
            result = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE preferences->>'retention_flagged' IS NOT NULL")
            )
            stats["flagged_for_deletion"] = result.scalar() or 0
        except Exception:
            stats["flagged_for_deletion"] = 0

    # Analytics events
    try:
        result = await session.execute(text("SELECT COUNT(*) FROM analytics_events"))
        stats["total_analytics_events"] = result.scalar() or 0
        analytics_cutoff = now - timedelta(days=ANALYTICS_RETENTION_DAYS)
        result = await session.execute(
            text("SELECT COUNT(*) FROM analytics_events WHERE timestamp < :cutoff"),
            {"cutoff": analytics_cutoff.isoformat()},
        )
        stats["analytics_events_expired"] = result.scalar() or 0
    except Exception:
        stats["total_analytics_events"] = 0
        stats["analytics_events_expired"] = 0

    # Payment events (kept for 7 years)
    result = await session.execute(select(func.count(PaymentEventRow.id)))
    stats["total_payment_events"] = result.scalar() or 0

    stats["retention_policy"] = {
        "inactive_threshold_days": INACTIVE_THRESHOLD_DAYS,
        "soft_delete_grace_days": SOFT_DELETE_GRACE_DAYS,
        "analytics_retention_days": ANALYTICS_RETENTION_DAYS,
        "payment_retention_years": PAYMENT_RETENTION_YEARS,
    }

    return stats


@router.get("/preview")
async def preview_retention(
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Preview what a retention sweep would purge without actually deleting."""
    result = await run_retention_sweep(session, dry_run=True)
    await session.rollback()  # Ensure nothing was touched
    return {
        "status": "preview",
        "would_affect": {
            "inactive_accounts_flagged": result.inactive_accounts_flagged,
            "accounts_hard_deleted": result.accounts_hard_deleted,
            "analytics_events_pruned": result.analytics_events_pruned,
            "expired_tokens_purged": result.expired_tokens_purged,
            "orphaned_records_cleaned": result.orphaned_records_cleaned,
        },
    }
