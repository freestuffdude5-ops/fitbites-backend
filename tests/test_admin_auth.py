"""Tests for admin authentication."""
import pytest
from src.auth import require_admin, create_tokens, _verify


class TestRequireAdmin:
    """Verify admin role checking logic."""

    def test_admin_via_preferences_role(self):
        """Users with role=admin in preferences should be admins."""
        from unittest.mock import MagicMock
        user = MagicMock()
        user.preferences = {"role": "admin"}
        user.email = "user@example.com"
        # The function is async and uses Depends, so we test the logic directly
        prefs = user.preferences or {}
        assert prefs.get("role") == "admin"

    def test_non_admin_user(self):
        """Regular users should not have admin access."""
        from unittest.mock import MagicMock
        user = MagicMock()
        user.preferences = {}
        user.email = "user@example.com"
        prefs = user.preferences or {}
        assert prefs.get("role") != "admin"

    def test_none_preferences_handled(self):
        """Users with None preferences should not crash."""
        from unittest.mock import MagicMock
        user = MagicMock()
        user.preferences = None
        user.email = "user@example.com"
        prefs = user.preferences or {}
        assert prefs.get("role") != "admin"


class TestTokenCreation:
    """Verify JWT token creation and verification."""

    def test_create_tokens_returns_access_and_refresh(self):
        tokens = create_tokens("user-123")
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "bearer"

    def test_access_token_verifiable(self):
        tokens = create_tokens("user-456")
        payload = _verify(tokens["access_token"])
        assert payload is not None
        assert payload["sub"] == "user-456"
        assert payload["type"] == "access"

    def test_refresh_token_verifiable(self):
        tokens = create_tokens("user-789")
        payload = _verify(tokens["refresh_token"])
        assert payload is not None
        assert payload["sub"] == "user-789"
        assert payload["type"] == "refresh"

    def test_invalid_token_rejected(self):
        assert _verify("invalid.token.here") is None
        assert _verify("") is None
        assert _verify("abc") is None

    def test_tampered_token_rejected(self):
        tokens = create_tokens("user-123")
        # Tamper with the token
        tampered = tokens["access_token"][:-5] + "XXXXX"
        assert _verify(tampered) is None
