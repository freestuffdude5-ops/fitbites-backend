"""Tests for the FitBites Data Retention Service."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from src.services.data_retention import (
    RetentionResult,
    INACTIVE_THRESHOLD_DAYS,
    SOFT_DELETE_GRACE_DAYS,
    ANALYTICS_RETENTION_DAYS,
    SESSION_TOKEN_MAX_AGE_DAYS,
    PAYMENT_RETENTION_YEARS,
)


class TestRetentionConfig:
    """Verify retention policy constants are sensible."""

    def test_inactive_threshold_is_24_months(self):
        assert INACTIVE_THRESHOLD_DAYS == 730

    def test_grace_period_is_30_days(self):
        assert SOFT_DELETE_GRACE_DAYS == 30

    def test_analytics_retention_is_12_months(self):
        assert ANALYTICS_RETENTION_DAYS == 365

    def test_session_token_max_age_is_90_days(self):
        assert SESSION_TOKEN_MAX_AGE_DAYS == 90

    def test_payment_retention_is_7_years(self):
        """IRS requires 7 years for financial records."""
        assert PAYMENT_RETENTION_YEARS == 7


class TestRetentionResult:
    """Verify the result dataclass."""

    def test_default_values(self):
        r = RetentionResult()
        assert r.inactive_accounts_flagged == 0
        assert r.accounts_hard_deleted == 0
        assert r.analytics_events_pruned == 0
        assert r.expired_tokens_purged == 0
        assert r.orphaned_records_cleaned == 0
        assert r.errors == []
        assert r.dry_run is False

    def test_serializable(self):
        r = RetentionResult(
            inactive_accounts_flagged=5,
            accounts_hard_deleted=2,
            dry_run=True,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            duration_ms=1000,
        )
        d = asdict(r)
        assert d["inactive_accounts_flagged"] == 5
        assert d["dry_run"] is True
        assert d["duration_ms"] == 1000

    def test_errors_are_mutable_list(self):
        r = RetentionResult()
        r.errors.append("test error")
        assert len(r.errors) == 1
        # Verify default factory creates new list per instance
        r2 = RetentionResult()
        assert len(r2.errors) == 0


class TestRetentionPolicyLogic:
    """Test the business logic without DB — verify cutoff calculations."""

    def test_inactive_cutoff_is_correct(self):
        now = datetime(2026, 2, 25, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=INACTIVE_THRESHOLD_DAYS)
        # 730 days before Feb 25, 2026 = ~Feb 25, 2024
        assert cutoff.year == 2024
        assert cutoff.month == 2

    def test_analytics_cutoff_is_correct(self):
        now = datetime(2026, 2, 25, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=ANALYTICS_RETENTION_DAYS)
        # 365 days before = ~Feb 25, 2025
        assert cutoff.year == 2025

    def test_grace_period_calculation(self):
        flagged_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        delete_after = flagged_at + timedelta(days=SOFT_DELETE_GRACE_DAYS)
        assert delete_after.month == 1
        assert delete_after.day == 31

    def test_payment_retention_covers_irs_requirement(self):
        """Payment events should be kept for at least 7 years (IRS)."""
        assert PAYMENT_RETENTION_YEARS >= 7
        retention_days = PAYMENT_RETENTION_YEARS * 365
        assert retention_days >= 2555  # ~7 years in days
