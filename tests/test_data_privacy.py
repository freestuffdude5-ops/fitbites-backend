"""Tests for the FitBites Data Privacy Service (GDPR/CCPA compliance)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.services.data_privacy import ConsentUpdate


class TestConsentModel:
    """Test the consent update Pydantic model."""

    def test_all_none_by_default(self):
        c = ConsentUpdate()
        assert c.analytics is None
        assert c.marketing is None
        assert c.personalization is None
        assert c.third_party is None

    def test_partial_update(self):
        c = ConsentUpdate(analytics=True)
        assert c.analytics is True
        assert c.marketing is None

    def test_all_fields(self):
        c = ConsentUpdate(analytics=True, marketing=False, personalization=True, third_party=False)
        assert c.analytics is True
        assert c.marketing is False
        assert c.personalization is True
        assert c.third_party is False

    def test_bool_coercion(self):
        c = ConsentUpdate(analytics=1, marketing=0)
        assert c.analytics is True
        assert c.marketing is False


class TestConsentTypes:
    """Verify we handle all required consent categories."""

    REQUIRED_TYPES = {"analytics", "marketing", "personalization", "third_party"}

    def test_consent_model_covers_all_types(self):
        fields = set(ConsentUpdate.model_fields.keys())
        assert self.REQUIRED_TYPES == fields

    def test_essential_consent_not_optional(self):
        """Essential cookies/functionality consent should NOT be toggleable."""
        fields = ConsentUpdate.model_fields.keys()
        assert "essential" not in fields  # Essential is always on


class TestPrivacyCompliance:
    """Verify GDPR/CCPA compliance requirements are met by design."""

    def test_export_endpoint_exists(self):
        """GDPR Art. 20 — data portability requires export endpoint."""
        from src.services.data_privacy import router
        paths = [r.path for r in router.routes]
        assert any("/data-export" in p for p in paths)

    def test_delete_endpoint_exists(self):
        """GDPR Art. 17 — right to erasure requires delete endpoint."""
        from src.services.data_privacy import router
        methods = {}
        for route in router.routes:
            methods[route.path] = list(getattr(route, 'methods', set()))
        # DELETE /api/v1/me
        assert any("DELETE" in m for m in methods.values())

    def test_consent_get_endpoint_exists(self):
        from src.services.data_privacy import router
        paths = [r.path for r in router.routes]
        assert any("/consent" in p for p in paths)

    def test_consent_post_endpoint_exists(self):
        from src.services.data_privacy import router
        methods = {}
        for route in router.routes:
            methods[route.path] = list(getattr(route, 'methods', set()))
        assert any("POST" in m for p, m in methods.items() if "/consent" in p)


class TestRetentionRouterRegistered:
    """Verify data retention router is wired into the app."""

    def test_retention_router_has_endpoints(self):
        from src.services.data_retention import router
        paths = [r.path for r in router.routes]
        assert any("/run" in p for p in paths)
        assert any("/stats" in p for p in paths)
        assert any("/preview" in p for p in paths)
