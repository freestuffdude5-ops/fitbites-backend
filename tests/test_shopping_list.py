"""Tests for shopping list API."""
import pytest

from tests.conftest import TestSession
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow
from src.auth import create_tokens
from src.models import Platform


def _auth(user_id: str) -> dict:
    tokens = create_tokens(user_id)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _setup(session):
    """Create test user and recipes with ingredients."""
    user = UserRow(id="shop-user", email="shop@test.com", display_name="Shopper", preferences={})
    session.add(user)

    session.add(RecipeRow(
        id="r-chicken", title="Grilled Chicken", description="Simple grilled chicken",
        creator_username="chef1", creator_platform=Platform.REDDIT,
        creator_profile_url="https://reddit.com/u/chef1",
        platform=Platform.REDDIT, source_url="https://reddit.com/1",
        calories=350, protein_g=40, tags=["high-protein"],
        virality_score=80.0,
        ingredients=[
            {"name": "chicken breast", "quantity": "2", "unit": "lb"},
            {"name": "olive oil", "quantity": "2", "unit": "tbsp"},
            {"name": "garlic", "quantity": "3", "unit": "clove"},
            {"name": "salt", "quantity": "1", "unit": "tsp"},
        ],
    ))
    session.add(RecipeRow(
        id="r-salad", title="Greek Salad", description="Fresh greek salad",
        creator_username="chef2", creator_platform=Platform.REDDIT,
        creator_profile_url="https://reddit.com/u/chef2",
        platform=Platform.REDDIT, source_url="https://reddit.com/2",
        calories=200, protein_g=8, tags=["low-cal"],
        virality_score=70.0,
        ingredients=[
            {"name": "olive oil", "quantity": "3", "unit": "tablespoons"},
            {"name": "cucumber", "quantity": "1", "unit": "piece"},
            {"name": "feta cheese", "quantity": "4", "unit": "oz"},
            {"name": "garlic", "quantity": "1", "unit": "cloves"},
        ],
    ))
    await session.commit()
    return _auth("shop-user")


@pytest.mark.asyncio
async def test_shopping_list_aggregates_ingredients(client):
    async with TestSession() as s:
        headers = await _setup(s)

    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["r-chicken", "r-salad"]},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["recipe_count"] == 2
    assert data["total_items"] > 0

    # Olive oil should be merged (2 tbsp + 3 tbsp = 5 tbsp)
    oil = next((i for i in data["items"] if i["name"].lower() == "olive oil"), None)
    assert oil is not None
    assert "5" in oil["total_quantity"]
    assert len(oil["from_recipes"]) == 2

    # Garlic should be merged (3 + 1 = 4 cloves)
    garlic = next((i for i in data["items"] if i["name"].lower() == "garlic"), None)
    assert garlic is not None
    assert "4" in garlic["total_quantity"]


@pytest.mark.asyncio
async def test_shopping_list_with_multiplier(client):
    async with TestSession() as s:
        headers = await _setup(s)

    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["r-chicken"], "servings_multiplier": 2.0},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    chicken = next((i for i in data["items"] if "chicken" in i["name"].lower()), None)
    assert chicken is not None
    assert "4" in chicken["total_quantity"]  # 2 lb * 2 = 4 lb


@pytest.mark.asyncio
async def test_shopping_list_has_affiliate_links(client):
    async with TestSession() as s:
        headers = await _setup(s)

    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["r-chicken"]},
        headers=headers,
    )
    data = r.json()
    for item in data["items"]:
        assert "amazon.com" in item["affiliate_url"]
        assert "83apps01-20" in item["affiliate_url"]


@pytest.mark.asyncio
async def test_shopping_list_requires_auth(client):
    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["r-chicken"]},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_shopping_list_404_no_recipes(client):
    async with TestSession() as s:
        headers = await _setup(s)

    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["nonexistent"]},
        headers=headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_shopping_list_single_recipe(client):
    async with TestSession() as s:
        headers = await _setup(s)

    r = await client.post(
        "/api/v1/shopping-list",
        json={"recipe_ids": ["r-salad"]},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["recipe_count"] == 1
    assert data["total_items"] == 4
