"""Tests for FitBites API endpoints using httpx async test client."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app, _last_scrape_time
from src.models import Recipe, Creator, NutritionInfo, Ingredient, Platform
from src.db.repository import RecipeRepository


def _make_recipe(title: str = "Test Recipe", calories: int = 300, protein: float = 25.0, platform: str = "youtube", virality: float = 85.0) -> Recipe:
    return Recipe(
        id=f"api-test-{title.lower().replace(' ', '-')}",
        title=title,
        description=f"A healthy {title}",
        creator=Creator(username="chef123", display_name="Chef", platform=platform, profile_url="https://example.com"),
        platform=Platform(platform),
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        ingredients=[Ingredient(name="chicken", quantity="200g")],
        steps=["Step 1", "Step 2"],
        nutrition=NutritionInfo(calories=calories, protein_g=protein, carbs_g=20, fat_g=10),
        views=100000,
        likes=5000,
        tags=["high-protein", "low-calorie"],
        virality_score=virality,
    )


async def _seed_recipes(count: int = 3):
    """Insert test recipes into the DB."""
    from conftest import TestSession
    async with TestSession() as session:
        repo = RecipeRepository(session)
        for i in range(count):
            recipe = _make_recipe(title=f"Recipe {i}", calories=200 + i * 100, protein=20 + i * 5, virality=90 - i * 10)
            await repo.upsert(recipe)
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "FitBites"
    assert "recipes" in data


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert data["version"] == "0.2.0"


@pytest.mark.asyncio
async def test_list_recipes_default(client):
    """Verify recipes endpoint returns data (conftest seeds 1 recipe)."""
    resp = await client.get("/api/v1/recipes")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert body["pagination"]["total"] >= 1


@pytest.mark.asyncio
async def test_list_recipes_with_data(client):
    await _seed_recipes(3)
    resp = await client.get("/api/v1/recipes?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total"] == 4  # 3 seeded + 1 from conftest
    assert body["pagination"]["has_more"] is True


@pytest.mark.asyncio
async def test_list_recipes_pagination_offset(client):
    await _seed_recipes(3)
    resp = await client.get("/api/v1/recipes?limit=2&offset=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2  # 4 total, offset 2, limit 2 → 2 remaining
    assert body["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_get_recipe_not_found(client):
    resp = await client.get("/api/v1/recipes/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_recipes_with_pagination(client):
    await _seed_recipes(3)
    resp = await client.get("/api/v1/recipes/search?q=Recipe&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["has_more"] is True


@pytest.mark.asyncio
async def test_search_no_results(client):
    resp = await client.get("/api/v1/recipes/search?q=nonexistent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["pagination"]["total"] == 0


@pytest.mark.asyncio
async def test_affiliate_links(client):
    resp = await client.post("/api/v1/affiliate-links", json=["chicken breast", "olive oil"])
    assert resp.status_code == 200
    data = resp.json()
    # New format includes compliance metadata
    assert "ingredients" in data
    assert "compliance" in data
    assert isinstance(data["ingredients"], list)
    assert len(data["ingredients"]) == 2
    # Verify compliance disclosure present
    assert data["compliance"]["has_affiliate_links"] is True
    assert "disclosure" in data["compliance"]
