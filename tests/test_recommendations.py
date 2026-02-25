"""Tests for recommendation engine and personalized feed."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow, SavedRecipeRow
from src.models import Platform

from tests.conftest import get_test_session


async def _seed_user_and_recipes(session):
    """Seed a user and diverse recipes for testing recommendations."""
    user = UserRow(
        id="rec-user-1",
        device_id="rec-device-1",
        preferences={"dietary": ["high-protein"], "max_calories": 600, "min_protein": 25},
    )
    session.add(user)

    recipes = [
        RecipeRow(
            id=f"rec-recipe-{i}",
            title=title,
            description=desc,
            creator_username="chef",
            creator_platform=Platform.YOUTUBE,
            creator_profile_url="https://youtube.com/@chef",
            platform=Platform.YOUTUBE,
            source_url=f"https://youtube.com/watch?v=rec{i}",
            ingredients=[{"name": "chicken breast", "quantity": "200g"}],
            steps=["Cook it"],
            tags=tags,
            calories=cals,
            protein_g=prot,
            carbs_g=30,
            fat_g=10,
            virality_score=viral,
        )
        for i, (title, desc, tags, cals, prot, viral) in enumerate([
            ("Grilled Chicken Bowl", "High protein bowl", ["high-protein", "meal-prep"], 450, 45, 92),
            ("Keto Salmon Plate", "Low carb salmon", ["keto", "high-protein"], 380, 35, 88),
            ("Vegan Buddha Bowl", "Plant-based goodness", ["vegan", "low-calorie"], 320, 15, 75),
            ("Protein Pancakes", "Fluffy protein pancakes", ["high-protein", "breakfast"], 400, 32, 85),
            ("Caesar Salad", "Classic caesar", ["low-calorie", "quick"], 280, 22, 70),
            ("Pasta Carbonara", "Creamy pasta", ["comfort-food"], 800, 25, 95),  # Over calorie limit
            ("Steak & Veggies", "Grilled steak", ["high-protein", "dinner"], 550, 48, 90),
            ("Smoothie Bowl", "Berry smoothie", ["breakfast", "low-calorie"], 250, 12, 65),
        ])
    ]
    for r in recipes:
        session.add(r)

    # Save some recipes to build affinity
    for rid in ["rec-recipe-0", "rec-recipe-1", "rec-recipe-3"]:
        session.add(SavedRecipeRow(id=f"save-{rid}", user_id="rec-user-1", recipe_id=rid))

    await session.commit()
    return user


@pytest.mark.asyncio
async def test_personalized_feed_returns_recipes():
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "pagination" in data
        # Should get recipes (excluding saved ones by default)
        assert len(data["data"]) > 0


@pytest.mark.asyncio
async def test_personalized_feed_excludes_saved():
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1?exclude_saved=true")
        data = resp.json()
        saved_ids = {"rec-recipe-0", "rec-recipe-1", "rec-recipe-3"}
        returned_ids = {r["id"] for r in data["data"]}
        assert not (returned_ids & saved_ids), "Saved recipes should be excluded"


@pytest.mark.asyncio
async def test_personalized_feed_includes_saved_when_requested():
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1?exclude_saved=false")
        data = resp.json()
        returned_ids = {r["id"] for r in data["data"]}
        assert "rec-recipe-0" in returned_ids


@pytest.mark.asyncio
async def test_feed_respects_calorie_limit():
    """Recipes over user's max_calories should be filtered or penalized."""
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1?exclude_saved=false")
        data = resp.json()
        # Pasta Carbonara (800 cal) should be filtered out (user max = 600)
        returned_ids = {r["id"] for r in data["data"]}
        assert "rec-recipe-5" not in returned_ids


@pytest.mark.asyncio
async def test_feed_boosts_high_protein():
    """High-protein recipes should rank higher for users with high-protein preference."""
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1?exclude_saved=false&limit=3")
        data = resp.json()
        # Top results should lean high-protein
        top_ids = [r["id"] for r in data["data"][:3]]
        # Steak & Veggies (48g protein) or Grilled Chicken (45g) should be near top
        assert any(rid in top_ids for rid in ["rec-recipe-0", "rec-recipe-6"])


@pytest.mark.asyncio
async def test_feed_has_rich_response_format():
    async with get_test_session() as session:
        await _seed_user_and_recipes(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/rec-user-1?exclude_saved=false&limit=1")
        data = resp.json()
        item = data["data"][0]
        # Verify rich feed item format
        assert "id" in item
        assert "title" in item
        assert "creator" in item
        assert "nutrition" in item
        assert "relevance_score" in item
        assert "tags" in item
        assert "ingredient_count" in item


@pytest.mark.asyncio
async def test_feed_404_for_missing_user():
    async with get_test_session() as session:
        pass  # empty DB

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/feed/nonexistent")
        assert resp.status_code == 404
