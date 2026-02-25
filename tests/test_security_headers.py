"""Tests for security headers middleware."""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest.mark.asyncio
async def test_security_headers_present():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-xss-protection"] == "1; mode=block"
        assert "strict-origin" in resp.headers["referrer-policy"]
        assert "camera=()" in resp.headers["permissions-policy"]
        assert "max-age=31536000" in resp.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_auth_endpoints_no_cache():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "wrong"})
        assert "no-store" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_public_endpoints_no_strict_cache():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/recipes?limit=1")
        # Public endpoints should NOT have no-store
        cache_control = resp.headers.get("cache-control", "")
        assert "no-store" not in cache_control
