"""Tests for reviews, ratings, cooking history, and search suggestions."""
import pytest

from tests.conftest import TestSession
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow
from src.models import Platform


async def _setup_user(session, user_id="u1", email="reviewer@test.com"):
    """Create a test user."""
    user = UserRow(id=user_id, email=email, display_name="Reviewer", preferences={})
    session.add(user)
    await session.commit()
    return user_id


async def _setup_extra_recipe(session):
    """Add a second recipe for diversity tests."""
    session.add(RecipeRow(
        id="r2", title="Greek Yogurt Bowl", description="Creamy yogurt",
        creator_username="healthchef", creator_platform=Platform.REDDIT,
        creator_profile_url="https://reddit.com/u/healthchef",
        platform=Platform.REDDIT, source_url="https://reddit.com/1",
        calories=200, protein_g=25, tags=["high-protein", "snack"],
        virality_score=70.0, ingredients=[{"name": "greek yogurt"}],
    ))
    await session.commit()


# ── Review Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_review(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    r = await client.post(
        f"/api/v1/recipes/test-recipe-1/reviews?user_id={uid}",
        json={"rating": 5, "title": "Amazing!", "body": "Best ever", "made_it": True},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["rating"] == 5
    assert data["made_it"] is True
    assert data["user"]["display_name"] == "Reviewer"


@pytest.mark.asyncio
async def test_duplicate_review_rejected(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    await client.post(f"/api/v1/recipes/test-recipe-1/reviews?user_id={uid}", json={"rating": 4})
    r = await client.post(f"/api/v1/recipes/test-recipe-1/reviews?user_id={uid}", json={"rating": 5})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_reviews_with_summary(client):
    async with TestSession() as s:
        await _setup_user(s, "u1", "a@test.com")
        await _setup_user(s, "u2", "b@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u1", json={"rating": 5, "made_it": True})
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u2", json={"rating": 3})

    r = await client.get("/api/v1/recipes/test-recipe-1/reviews")
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["total_reviews"] == 2
    assert data["summary"]["average_rating"] == 4.0
    assert data["summary"]["made_it_count"] == 1


@pytest.mark.asyncio
async def test_update_review(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    create_r = await client.post(
        f"/api/v1/recipes/test-recipe-1/reviews?user_id={uid}", json={"rating": 3}
    )
    review_id = create_r.json()["id"]
    r = await client.patch(
        f"/api/v1/recipes/test-recipe-1/reviews/{review_id}?user_id={uid}",
        json={"rating": 5, "title": "Updated!"},
    )
    assert r.status_code == 200
    assert r.json()["rating"] == 5


@pytest.mark.asyncio
async def test_delete_review(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    create_r = await client.post(
        f"/api/v1/recipes/test-recipe-1/reviews?user_id={uid}", json={"rating": 4}
    )
    review_id = create_r.json()["id"]
    r = await client.delete(f"/api/v1/recipes/test-recipe-1/reviews/{review_id}?user_id={uid}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_helpful_toggle(client):
    async with TestSession() as s:
        await _setup_user(s, "u1", "a@test.com")
        await _setup_user(s, "u2", "b@test.com")
    create_r = await client.post(
        "/api/v1/recipes/test-recipe-1/reviews?user_id=u1", json={"rating": 5}
    )
    review_id = create_r.json()["id"]

    r = await client.post(f"/api/v1/reviews/{review_id}/helpful?user_id=u2")
    assert r.status_code == 200
    assert r.json()["status"] == "added"
    assert r.json()["helpful_count"] == 1

    r = await client.post(f"/api/v1/reviews/{review_id}/helpful?user_id=u2")
    assert r.json()["status"] == "removed"
    assert r.json()["helpful_count"] == 0


@pytest.mark.asyncio
async def test_recipe_rating_summary(client):
    async with TestSession() as s:
        await _setup_user(s, "u1", "a@test.com")
        await _setup_user(s, "u2", "b@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u1", json={"rating": 5, "made_it": True})
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u2", json={"rating": 4})

    r = await client.get("/api/v1/recipes/test-recipe-1/rating")
    assert r.status_code == 200
    data = r.json()
    assert data["total_reviews"] == 2
    assert data["average_rating"] == 4.5
    assert data["made_it_count"] == 1


@pytest.mark.asyncio
async def test_review_sort_options(client):
    async with TestSession() as s:
        await _setup_user(s, "u1", "a@test.com")
        await _setup_user(s, "u2", "b@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u1", json={"rating": 5})
    await client.post("/api/v1/recipes/test-recipe-1/reviews?user_id=u2", json={"rating": 2})

    for sort in ["newest", "highest", "lowest", "helpful"]:
        r = await client.get(f"/api/v1/recipes/test-recipe-1/reviews?sort={sort}")
        assert r.status_code == 200
        assert len(r.json()["data"]) == 2


# ── Cooking History Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_cooking(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    r = await client.post(
        f"/api/v1/users/{uid}/cooking-log?recipe_id=test-recipe-1",
        json={"servings": 2, "notes": "Extra protein", "rating": 5},
    )
    assert r.status_code == 201
    assert r.json()["recipe"]["title"] == "Test Chicken Bowl"
    assert r.json()["servings"] == 2


@pytest.mark.asyncio
async def test_cooking_history_list(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
        await _setup_extra_recipe(s)
    await client.post(f"/api/v1/users/{uid}/cooking-log?recipe_id=test-recipe-1", json={"servings": 1})
    await client.post(f"/api/v1/users/{uid}/cooking-log?recipe_id=r2", json={"servings": 1})

    r = await client.get(f"/api/v1/users/{uid}/cooking-log")
    assert r.status_code == 200
    data = r.json()
    assert data["stats"]["total_cooked"] == 2
    assert data["stats"]["unique_recipes"] == 2


@pytest.mark.asyncio
async def test_cooking_stats(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
        await _setup_extra_recipe(s)
    await client.post(f"/api/v1/users/{uid}/cooking-log?recipe_id=test-recipe-1", json={"servings": 1})
    await client.post(f"/api/v1/users/{uid}/cooking-log?recipe_id=test-recipe-1", json={"servings": 2})
    await client.post(f"/api/v1/users/{uid}/cooking-log?recipe_id=r2", json={"servings": 1})

    r = await client.get(f"/api/v1/users/{uid}/cooking-stats?days=7")
    assert r.status_code == 200
    data = r.json()
    assert data["meals_cooked"] == 3
    assert data["unique_recipes"] == 2
    assert data["streak"] >= 1
    assert len(data["top_recipes"]) >= 1


# ── Search Suggestions Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_suggestions_with_query(client):
    r = await client.get("/api/v1/search/suggestions?q=chicken")
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "chicken"
    assert len(data["suggestions"]) > 0


@pytest.mark.asyncio
async def test_search_suggestions_short_returns_trending(client):
    r = await client.get("/api/v1/search/suggestions?q=x")
    assert r.status_code == 200
    assert "trending_tags" in r.json()


@pytest.mark.asyncio
async def test_trending_tags(client):
    r = await client.get("/api/v1/trending/tags")
    assert r.status_code == 200
    data = r.json()
    assert "trending_tags" in data
    tag_names = [t["tag"] for t in data["trending_tags"]]
    assert "high-protein" in tag_names


@pytest.mark.asyncio
async def test_review_nonexistent_recipe(client):
    async with TestSession() as s:
        uid = await _setup_user(s)
    r = await client.post(
        f"/api/v1/recipes/nonexistent/reviews?user_id={uid}",
        json={"rating": 5},
    )
    assert r.status_code == 404
