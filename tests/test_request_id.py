"""Tests for request ID tracing middleware."""
import pytest
from httpx import ASGITransport, AsyncClient
from src.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_response_includes_request_id(client):
    """Every response should have X-Request-ID header."""
    resp = await client.get("/health")
    assert "x-request-id" in resp.headers
    # Should be a valid UUID4-ish string
    rid = resp.headers["x-request-id"]
    assert len(rid) == 36  # UUID format


@pytest.mark.asyncio
async def test_client_request_id_honored(client):
    """If client sends X-Request-ID, server should echo it back."""
    custom_id = "my-trace-12345"
    resp = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["x-request-id"] == custom_id


@pytest.mark.asyncio
async def test_unique_ids_per_request(client):
    """Each request gets a unique ID."""
    r1 = await client.get("/health")
    r2 = await client.get("/health")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
