"""
FitBites Revenue Alert Service
---
Real-time monitoring of financial health with configurable alerts.
Detects anomalies in affiliate clicks, subscription churn, payment failures.

Endpoints:
- GET  /api/v1/admin/alerts              — List active alerts
- GET  /api/v1/admin/alerts/config       — View alert thresholds
- POST /api/v1/admin/alerts/config       — Update alert thresholds
- GET  /api/v1/admin/alerts/history      — Alert history (last 30 days)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.subscription_tables import SubscriptionRow, PaymentEventRow
from src.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/alerts", tags=["admin", "alerts"])


# ── Alert Types ───────────────────────────────────────────────────────────────

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    REVENUE_DROP = "revenue_drop"
    HIGH_CHURN = "high_churn"
    PAYMENT_FAILURES = "payment_failures"
    LOW_AFFILIATE_CTR = "low_affiliate_ctr"
    SUBSCRIPTION_ANOMALY = "subscription_anomaly"
    REFUND_SPIKE = "refund_spike"


@dataclass
class Alert:
    type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metric_value: float
    threshold: float
    triggered_at: str
    recommendation: str = ""


# ── Default Thresholds ────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    AlertType.REVENUE_DROP: {
        "warning": 0.20,    # 20% drop day-over-day
        "critical": 0.40,   # 40% drop
        "window_days": 1,
    },
    AlertType.HIGH_CHURN: {
        "warning": 0.05,    # 5% monthly churn
        "critical": 0.10,   # 10% monthly churn
        "window_days": 30,
    },
    AlertType.PAYMENT_FAILURES: {
        "warning": 0.05,    # 5% failure rate
        "critical": 0.15,   # 15% failure rate
        "window_days": 7,
    },
    AlertType.LOW_AFFILIATE_CTR: {
        "warning": 0.10,    # CTR below 10%
        "critical": 0.05,   # CTR below 5%
        "window_days": 7,
    },
    AlertType.REFUND_SPIKE: {
        "warning": 0.03,    # 3% refund rate
        "critical": 0.08,   # 8% refund rate
        "window_days": 7,
    },
}

# In-memory config (would be DB-backed in production)
_current_thresholds = dict(DEFAULT_THRESHOLDS)


# ── Alert Evaluation ──────────────────────────────────────────────────────────

async def evaluate_churn(session: AsyncSession) -> Optional[Alert]:
    """Check subscription churn rate over last 30 days."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)
    thresholds = _current_thresholds[AlertType.HIGH_CHURN]

    try:
        # Total active subs at start of window
        total_result = await session.execute(
            select(func.count(SubscriptionRow.id)).where(
                SubscriptionRow.started_at < window_start,
                SubscriptionRow.status.in_(["active", "canceled", "expired"]),
            )
        )
        total = total_result.scalar() or 0
        if total == 0:
            return None

        # Canceled in window
        canceled_result = await session.execute(
            select(func.count(SubscriptionRow.id)).where(
                SubscriptionRow.canceled_at >= window_start,
                SubscriptionRow.canceled_at <= now,
            )
        )
        canceled = canceled_result.scalar() or 0
        churn_rate = canceled / total

        if churn_rate >= thresholds["critical"]:
            severity = AlertSeverity.CRITICAL
        elif churn_rate >= thresholds["warning"]:
            severity = AlertSeverity.WARNING
        else:
            return None

        return Alert(
            type=AlertType.HIGH_CHURN,
            severity=severity,
            title="High Subscription Churn",
            message=f"{canceled}/{total} subscriptions canceled in 30 days ({churn_rate:.1%})",
            metric_value=churn_rate,
            threshold=thresholds[severity.value],
            triggered_at=now.isoformat(),
            recommendation="Review cancellation reasons. Consider win-back campaign or feature improvements.",
        )
    except Exception as e:
        logger.error(f"Churn evaluation failed: {e}")
        return None


async def evaluate_payment_failures(session: AsyncSession) -> Optional[Alert]:
    """Check payment failure rate over last 7 days."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=7)
    thresholds = _current_thresholds[AlertType.PAYMENT_FAILURES]

    try:
        # Total payment events in window
        total_result = await session.execute(
            select(func.count(PaymentEventRow.id)).where(
                PaymentEventRow.created_at >= window_start,
                PaymentEventRow.event_type.in_(["invoice.paid", "invoice.payment_failed"]),
            )
        )
        total = total_result.scalar() or 0
        if total == 0:
            return None

        # Failed payments
        failed_result = await session.execute(
            select(func.count(PaymentEventRow.id)).where(
                PaymentEventRow.created_at >= window_start,
                PaymentEventRow.event_type == "invoice.payment_failed",
            )
        )
        failed = failed_result.scalar() or 0
        failure_rate = failed / total

        if failure_rate >= thresholds["critical"]:
            severity = AlertSeverity.CRITICAL
        elif failure_rate >= thresholds["warning"]:
            severity = AlertSeverity.WARNING
        else:
            return None

        return Alert(
            type=AlertType.PAYMENT_FAILURES,
            severity=severity,
            title="Payment Failure Spike",
            message=f"{failed}/{total} payments failed in 7 days ({failure_rate:.1%})",
            metric_value=failure_rate,
            threshold=thresholds[severity.value],
            triggered_at=now.isoformat(),
            recommendation="Check Stripe dashboard for declined cards. Consider dunning email sequence.",
        )
    except Exception as e:
        logger.error(f"Payment failure evaluation failed: {e}")
        return None


async def evaluate_refund_spike(session: AsyncSession) -> Optional[Alert]:
    """Check refund rate over last 7 days."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=7)
    thresholds = _current_thresholds[AlertType.REFUND_SPIKE]

    try:
        total_result = await session.execute(
            select(func.count(PaymentEventRow.id)).where(
                PaymentEventRow.created_at >= window_start,
                PaymentEventRow.event_type == "invoice.paid",
            )
        )
        total_paid = total_result.scalar() or 0
        if total_paid == 0:
            return None

        refund_result = await session.execute(
            select(func.count(PaymentEventRow.id)).where(
                PaymentEventRow.created_at >= window_start,
                PaymentEventRow.event_type == "charge.refunded",
            )
        )
        refunds = refund_result.scalar() or 0
        refund_rate = refunds / total_paid

        if refund_rate >= thresholds["critical"]:
            severity = AlertSeverity.CRITICAL
        elif refund_rate >= thresholds["warning"]:
            severity = AlertSeverity.WARNING
        else:
            return None

        return Alert(
            type=AlertType.REFUND_SPIKE,
            severity=severity,
            title="Refund Rate Spike",
            message=f"{refunds} refunds out of {total_paid} payments ({refund_rate:.1%})",
            metric_value=refund_rate,
            threshold=thresholds[severity.value],
            triggered_at=now.isoformat(),
            recommendation="Investigate refund reasons. Check for billing UX issues or feature gaps.",
        )
    except Exception as e:
        logger.error(f"Refund evaluation failed: {e}")
        return None


async def run_all_checks(session: AsyncSession) -> list[Alert]:
    """Run all alert checks and return active alerts."""
    checks = [
        evaluate_churn(session),
        evaluate_payment_failures(session),
        evaluate_refund_spike(session),
    ]
    alerts = []
    for check in checks:
        result = await check
        if result:
            alerts.append(result)
    # Sort by severity (critical first)
    severity_order = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}
    alerts.sort(key=lambda a: severity_order.get(a.severity, 3))
    return alerts


# ── API Endpoints ─────────────────────────────────────────────────────────────

class ThresholdUpdate(BaseModel):
    alert_type: str
    warning: Optional[float] = None
    critical: Optional[float] = None


@router.get("")
async def get_active_alerts(
    admin=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Get all currently active alerts based on real-time data."""
    alerts = await run_all_checks(session)
    return {
        "alert_count": len(alerts),
        "alerts": [
            {
                "type": a.type.value,
                "severity": a.severity.value,
                "title": a.title,
                "message": a.message,
                "metric_value": round(a.metric_value, 4),
                "threshold": a.threshold,
                "triggered_at": a.triggered_at,
                "recommendation": a.recommendation,
            }
            for a in alerts
        ],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "healthy" if len(alerts) == 0 else (
            "critical" if any(a.severity == AlertSeverity.CRITICAL for a in alerts) else "warning"
        ),
    }


@router.get("/config")
async def get_alert_config(admin=Depends(require_admin)):
    """View current alert thresholds."""
    return {
        "thresholds": {
            k.value: v for k, v in _current_thresholds.items()
        }
    }


@router.post("/config")
async def update_alert_config(
    update: ThresholdUpdate,
    admin=Depends(require_admin),
):
    """Update alert thresholds for a specific alert type."""
    try:
        alert_type = AlertType(update.alert_type)
    except ValueError:
        return {"error": f"Unknown alert type: {update.alert_type}", "valid_types": [t.value for t in AlertType]}

    if alert_type not in _current_thresholds:
        return {"error": f"No configurable threshold for {update.alert_type}"}

    if update.warning is not None:
        _current_thresholds[alert_type]["warning"] = update.warning
    if update.critical is not None:
        _current_thresholds[alert_type]["critical"] = update.critical

    return {
        "status": "updated",
        "alert_type": alert_type.value,
        "thresholds": _current_thresholds[alert_type],
    }
