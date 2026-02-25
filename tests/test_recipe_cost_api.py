"""Tests for Recipe Cost Estimation API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_cost_estimate_endpoint(client):
    async with client as c:
        resp = await c.post("/api/v1/recipes/cost-estimate", json={
            "ingredients": [
                "1 lb chicken breast",
                "2 cups rice",
                "1 tbsp olive oil",
                "1 tsp salt",
            ],
            "servings": 4,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost" in data
    assert "per_serving_cost" in data
    assert "is_budget_friendly" in data
    assert "ingredients" in data
    assert len(data["ingredients"]) == 4
    assert data["total_cost"] > 0
    assert data["servings"] == 4


@pytest.mark.asyncio
async def test_cost_estimate_default_servings(client):
    async with client as c:
        resp = await c.post("/api/v1/recipes/cost-estimate", json={
            "ingredients": ["1 banana", "1 cup oats"],
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["servings"] == 4  # default


@pytest.mark.asyncio
async def test_meal_plan_cost_endpoint(client):
    async with client as c:
        resp = await c.post("/api/v1/meal-plan/cost", json={
            "recipes": [
                {
                    "title": "Chicken & Rice",
                    "ingredients": ["1 lb chicken breast", "2 cups rice"],
                    "servings": 4,
                },
                {
                    "title": "Protein Shake",
                    "ingredients": ["1 scoop protein powder", "1 cup almond milk"],
                    "servings": 1,
                },
            ]
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "total_weekly_cost" in data
    assert "daily_average" in data
    assert "recipes" in data
    assert "savings_tip" in data
    assert len(data["recipes"]) == 2


@pytest.mark.asyncio
async def test_empty_ingredients(client):
    async with client as c:
        resp = await c.post("/api/v1/recipes/cost-estimate", json={
            "ingredients": [],
            "servings": 1,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 0
