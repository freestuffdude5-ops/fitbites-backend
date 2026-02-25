"""Tests for auth token refresh."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app


@pytest.mark.asyncio
async def test_signup_login_refresh_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup
        resp = await client.post("/api/v1/auth/signup", json={
            "email": "refresh-test@fitbites.com", "password": "SecureP@ss123", "display_name": "Test",
        })
        assert resp.status_code == 200
        tokens = resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Use refresh token
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert resp.status_code == 200
        new_tokens = resp.json()
        assert "access_token" in new_tokens
        assert new_tokens["access_token"] != tokens["access_token"]

        # Use new access token
        resp = await client.get("/api/v1/me/saved", headers={
            "Authorization": f"Bearer {new_tokens['access_token']}",
        })
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_refresh_with_invalid_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid-token",
        })
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails():
    """Using an access token as refresh should fail."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/signup", json={
            "email": "refresh-test2@fitbites.com", "password": "SecureP@ss123",
        })
        tokens = resp.json()

        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["access_token"],
        })
        assert resp.status_code == 401
