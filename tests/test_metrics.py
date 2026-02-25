"""Tests for Prometheus metrics middleware."""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app
from src.middleware.metrics import metrics, _normalize_path


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reset metrics state between tests."""
    metrics.request_count.clear()
    metrics.request_duration_sum.clear()
    metrics.request_duration_count.clear()
    metrics.active_requests = 0
    yield


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Make a request to generate metrics
        await client.get("/health")
        # Fetch metrics
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        assert "fitbites_http_requests_total" in body
        assert "fitbites_uptime_seconds" in body
        assert "fitbites_active_requests" in body


@pytest.mark.asyncio
async def test_metrics_track_requests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
        await client.get("/health")
        resp = await client.get("/metrics")
        body = resp.text
        # Should show 2 requests to /health (plus the metrics requests themselves)
        assert 'path="/health"' in body


@pytest.mark.asyncio
async def test_metrics_tracks_status_codes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/recipes/nonexistent-id-12345")
        resp = await client.get("/metrics")
        body = resp.text
        assert 'status="404"' in body


def test_normalize_path_collapses_ids():
    assert _normalize_path("/api/v1/recipes/12345") == "/api/v1/recipes/:id"
    assert _normalize_path("/go/abc123def456abc123def456") == "/go/:id"
    assert _normalize_path("/api/v1/recipes") == "/api/v1/recipes"
    assert _normalize_path("/health") == "/health"


@pytest.mark.asyncio
async def test_metrics_duration_recorded():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
        resp = await client.get("/metrics")
        body = resp.text
        assert "fitbites_http_request_duration_seconds_sum" in body
        assert "fitbites_http_request_duration_seconds_count" in body
