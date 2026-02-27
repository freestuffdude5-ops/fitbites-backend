"""Tests for Recipe Integration API — tracking, nutrition, favorites."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_recipe_nutrition(client):
    """GET /recipes/{id}/nutrition returns nutrition breakdown."""
    resp = await client.get("/api/v1/recipes/test-recipe-1/nutrition")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recipe_id"] == "test-recipe-1"
    assert data["title"] == "Test Chicken Bowl"
    assert data["full_recipe"]["calories"] == 400
    assert data["full_recipe"]["protein_g"] == 35
    assert data["half_recipe"]["calories"] == 200
    assert data["half_recipe"]["protein_g"] == 17.5


@pytest.mark.asyncio
async def test_nutrition_404(client):
    resp = await client.get("/api/v1/recipes/nonexistent/nutrition")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_log_to_tracker_full_portion(client, auth_headers):
    """Log a full recipe to today's tracker."""
    resp = await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1", "portion": 1.0, "meal_type": "lunch"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "logged"
    assert data["portion"] == 1.0
    assert data["logged_nutrition"]["calories"] == 400
    assert data["daily_totals"]["calories"] == 400


@pytest.mark.asyncio
async def test_log_to_tracker_half_portion(client, auth_headers):
    """Log half a recipe — macros should be halved."""
    resp = await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1", "portion": 0.5, "meal_type": "snack"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["logged_nutrition"]["calories"] == 200
    assert data["logged_nutrition"]["protein_g"] == 17.5


@pytest.mark.asyncio
async def test_log_accumulates_daily_totals(client, auth_headers):
    """Logging multiple meals accumulates daily totals."""
    await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1", "portion": 1.0, "meal_type": "breakfast"},
        headers=auth_headers,
    )
    resp = await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1", "portion": 0.5, "meal_type": "lunch"},
        headers=auth_headers,
    )
    data = resp.json()
    assert data["daily_totals"]["calories"] == 600  # 400 + 200
    assert data["daily_totals"]["protein_g"] == 52.5  # 35 + 17.5


@pytest.mark.asyncio
async def test_log_requires_auth(client):
    resp = await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_log_invalid_recipe(client, auth_headers):
    resp = await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "nonexistent"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_save_favorite(client, auth_headers):
    resp = await client.post(
        "/api/v1/recipes/save-favorite",
        json={"recipe_id": "test-recipe-1", "collection": "Meal Prep"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_save_favorite_duplicate(client, auth_headers):
    await client.post(
        "/api/v1/recipes/save-favorite",
        json={"recipe_id": "test-recipe-1"},
        headers=auth_headers,
    )
    resp = await client.post(
        "/api/v1/recipes/save-favorite",
        json={"recipe_id": "test-recipe-1"},
        headers=auth_headers,
    )
    assert resp.json()["status"] == "already_saved"


@pytest.mark.asyncio
async def test_get_my_favorites(client, auth_headers):
    # Save a recipe first
    await client.post(
        "/api/v1/recipes/save-favorite",
        json={"recipe_id": "test-recipe-1", "notes": "Great for lunches"},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/recipes/my-favorites", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["data"][0]["recipe_id"] == "test-recipe-1"
    assert data["data"][0]["notes"] == "Great for lunches"
    assert data["data"][0]["nutrition"]["calories"] == 400


@pytest.mark.asyncio
async def test_daily_log_empty(client, auth_headers):
    resp = await client.get("/api/v1/tracking/daily", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["calories"] == 0
    assert data["meals"] == []


@pytest.mark.asyncio
async def test_daily_log_with_meals(client, auth_headers):
    await client.post(
        "/api/v1/recipes/log-to-tracker",
        json={"recipe_id": "test-recipe-1", "portion": 1.0, "meal_type": "dinner"},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/tracking/daily", headers=auth_headers)
    data = resp.json()
    assert data["totals"]["calories"] == 400
    assert len(data["meals"]) == 1
    assert data["meals"][0]["meal_type"] == "dinner"
    assert data["meals"][0]["recipe_title"] == "Test Chicken Bowl"


@pytest.mark.asyncio
async def test_tracking_log_meal_endpoint(client, auth_headers):
    """ECHO integration endpoint /tracking/log-meal works same as log-to-tracker."""
    resp = await client.post(
        "/api/v1/tracking/log-meal",
        json={"recipe_id": "test-recipe-1", "portion": 1.0, "meal_type": "meal"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "logged"
