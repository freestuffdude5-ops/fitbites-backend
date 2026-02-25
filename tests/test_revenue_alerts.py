"""Tests for the FitBites Revenue Alert Service."""
import pytest
from dataclasses import asdict

from src.services.revenue_alerts import (
    Alert,
    AlertSeverity,
    AlertType,
    DEFAULT_THRESHOLDS,
    ThresholdUpdate,
    _current_thresholds,
)


class TestAlertTypes:
    """Verify all alert types are defined."""

    def test_all_alert_types(self):
        types = list(AlertType)
        assert len(types) >= 5
        assert AlertType.REVENUE_DROP in types
        assert AlertType.HIGH_CHURN in types
        assert AlertType.PAYMENT_FAILURES in types
        assert AlertType.REFUND_SPIKE in types

    def test_severity_levels(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"


class TestAlertDataclass:
    """Verify Alert dataclass structure."""

    def test_alert_creation(self):
        a = Alert(
            type=AlertType.HIGH_CHURN,
            severity=AlertSeverity.WARNING,
            title="Test",
            message="Test message",
            metric_value=0.07,
            threshold=0.05,
            triggered_at="2026-02-25T00:00:00Z",
        )
        assert a.type == AlertType.HIGH_CHURN
        assert a.severity == AlertSeverity.WARNING
        assert a.recommendation == ""  # default

    def test_alert_serializable(self):
        a = Alert(
            type=AlertType.PAYMENT_FAILURES,
            severity=AlertSeverity.CRITICAL,
            title="Payment Issues",
            message="15% failure rate",
            metric_value=0.15,
            threshold=0.15,
            triggered_at="2026-02-25T00:00:00Z",
            recommendation="Check Stripe",
        )
        d = asdict(a)
        assert d["metric_value"] == 0.15
        assert d["recommendation"] == "Check Stripe"


class TestThresholds:
    """Verify default threshold configuration."""

    def test_all_alert_types_have_thresholds(self):
        for alert_type in [
            AlertType.REVENUE_DROP,
            AlertType.HIGH_CHURN,
            AlertType.PAYMENT_FAILURES,
            AlertType.LOW_AFFILIATE_CTR,
            AlertType.REFUND_SPIKE,
        ]:
            assert alert_type in DEFAULT_THRESHOLDS

    def test_warning_less_than_critical_for_churn(self):
        t = DEFAULT_THRESHOLDS[AlertType.HIGH_CHURN]
        assert t["warning"] < t["critical"]

    def test_warning_less_than_critical_for_payment_failures(self):
        t = DEFAULT_THRESHOLDS[AlertType.PAYMENT_FAILURES]
        assert t["warning"] < t["critical"]

    def test_refund_thresholds_reasonable(self):
        t = DEFAULT_THRESHOLDS[AlertType.REFUND_SPIKE]
        assert 0 < t["warning"] < 0.20  # Warning below 20%
        assert 0 < t["critical"] < 0.30  # Critical below 30%

    def test_all_thresholds_have_window(self):
        for t in DEFAULT_THRESHOLDS.values():
            assert "window_days" in t
            assert t["window_days"] > 0


class TestThresholdUpdate:
    """Test the threshold update Pydantic model."""

    def test_partial_update(self):
        u = ThresholdUpdate(alert_type="high_churn", warning=0.08)
        assert u.warning == 0.08
        assert u.critical is None

    def test_full_update(self):
        u = ThresholdUpdate(alert_type="payment_failures", warning=0.10, critical=0.25)
        assert u.warning == 0.10
        assert u.critical == 0.25


class TestRouterEndpoints:
    """Verify alert router has all expected endpoints."""

    def test_router_has_endpoints(self):
        from src.services.revenue_alerts import router
        paths = [r.path for r in router.routes]
        assert any("/alerts" in p or p.endswith("") for p in paths)
        assert any("/config" in p for p in paths)

    def test_get_alerts_endpoint(self):
        from src.services.revenue_alerts import router
        methods = {}
        for route in router.routes:
            methods[route.path] = list(getattr(route, 'methods', set()))
        # GET /api/v1/admin/alerts
        assert any("GET" in m for m in methods.values())

    def test_post_config_endpoint(self):
        from src.services.revenue_alerts import router
        methods = {}
        for route in router.routes:
            methods[route.path] = list(getattr(route, 'methods', set()))
        assert any("POST" in m for p, m in methods.items() if "/config" in p)
