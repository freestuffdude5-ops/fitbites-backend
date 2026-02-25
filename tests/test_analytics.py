"""Tests for the analytics module — event tracking, metrics dashboard, funnel."""
from __future__ import annotations

import pytest


# --- Event Tracking Tests ---

@pytest.mark.asyncio
async def test_track_single_event(client):
    resp = await client.post("/api/v1/events", json={
        "event": "test_event",
        "user_id": "test-user",
        "platform": "web",
        "properties": {"key": "value"},
    })
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_track_batch_events(client):
    events = [
        {"event": "app_open", "user_id": f"batch-user-{i}", "platform": "ios"}
        for i in range(5)
    ]
    resp = await client.post("/api/v1/events/batch", json={"events": events})
    assert resp.status_code == 202
    data = resp.json()
    assert data["count"] == 5


@pytest.mark.asyncio
async def test_batch_max_100(client):
    events = [{"event": "spam", "user_id": "x"} for _ in range(101)]
    resp = await client.post("/api/v1/events/batch", json={"events": events})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_event_requires_name(client):
    resp = await client.post("/api/v1/events", json={"user_id": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    await client.post("/api/v1/events", json={
        "event": "recipe_view", "user_id": "u1", "platform": "ios",
    })
    resp = await client.get("/api/v1/admin/metrics?hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert "unique_users" in data
    assert "platforms" in data
    assert "top_recipes" in data
    assert "affiliate_clicks" in data
    assert "api_performance" in data


@pytest.mark.asyncio
async def test_funnel_endpoint(client):
    resp = await client.get("/api/v1/admin/metrics/funnel?hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "funnel" in data
    assert "conversion_rates" in data
    assert "app_open" in data["funnel"]
    assert "recipe_view" in data["funnel"]
    assert "affiliate_click" in data["funnel"]


@pytest.mark.asyncio
async def test_response_time_header(client):
    resp = await client.get("/api/v1/recipes")
    assert "x-response-time-ms" in resp.headers
    ms = float(resp.headers["x-response-time-ms"])
    assert ms > 0
    assert ms < 5000
