"""Test the featured recipes endpoint."""
import pytest


@pytest.mark.asyncio
async def test_featured_endpoint(client):
    """Featured endpoint returns 200."""
    resp = await client.get("/api/v1/recipes/featured?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert "total" in data
    # The seed recipe has only 2 ingredients (chicken, rice), so it won't qualify
    # for featured (needs 3+), which is correct behavior
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_featured_filters_low_ingredient_recipes(client):
    """Featured should only return recipes with 3+ ingredients."""
    resp = await client.get("/api/v1/recipes/featured")
    data = resp.json()
    for recipe in data["data"]:
        assert len(recipe.get("ingredients", [])) >= 3
