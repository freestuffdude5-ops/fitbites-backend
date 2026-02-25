"""Tests for auth + saved recipes + trending endpoints."""
from __future__ import annotations

import pytest

from tests.conftest import TestSession
from src.db.repository import RecipeRepository
from src.models import Recipe, Creator, NutritionInfo, Ingredient, Platform


def _make_recipe(title="Test Recipe", recipe_id="test-recipe-1") -> Recipe:
    return Recipe(
        id=recipe_id,
        title=title,
        description="A test recipe",
        creator=Creator(username="chef", display_name="Chef", platform="youtube", profile_url="https://example.com"),
        platform=Platform("youtube"),
        source_url=f"https://example.com/{recipe_id}",
        ingredients=[Ingredient(name="chicken", quantity="200g")],
        steps=["Step 1"],
        nutrition=NutritionInfo(calories=300, protein_g=25, carbs_g=20, fat_g=10),
        views=10000,
        tags=["high-protein"],
        virality_score=85.0,
    )


async def _signup(client, email="user@test.com", password="Pass123!"):
    resp = await client.post("/api/v1/auth/signup", json={"email": email, "password": password, "display_name": "Test"})
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    data = resp.json()
    return data["access_token"]


async def _seed_recipe(recipe_id="test-recipe-extra"):
    """Seed an additional recipe. Note: conftest already seeds 'test-recipe-1'."""
    async with TestSession() as session:
        repo = RecipeRepository(session)
        r = _make_recipe(recipe_id=recipe_id)
        r.source_url = f"https://example.com/{recipe_id}"
        await repo.upsert(r)
        await session.commit()


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_signup(client):
    resp = await client.post("/api/v1/auth/signup", json={"email": "new@test.com", "password": "Pass123!"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["email"] == "new@test.com"
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_signup_duplicate(client):
    await client.post("/api/v1/auth/signup", json={"email": "dup@test.com", "password": "Pass123!"})
    resp = await client.post("/api/v1/auth/signup", json={"email": "dup@test.com", "password": "Pass123!"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/api/v1/auth/signup", json={"email": "login@test.com", "password": "Pass123!"})
    resp = await client.post("/api/v1/auth/login", json={"email": "login@test.com", "password": "Pass123!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/signup", json={"email": "wrong@test.com", "password": "Pass123!"})
    resp = await client.post("/api/v1/auth/login", json={"email": "wrong@test.com", "password": "Wrong!"})
    assert resp.status_code == 401


# ── Save/Unsave ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_recipe(client):
    # test-recipe-1 is seeded by conftest
    token = await _signup(client, "save@test.com")
    resp = await client.post("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"


@pytest.mark.asyncio
async def test_save_recipe_idempotent(client):
    token = await _signup(client, "idem@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    resp = await client.post("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_saved"


@pytest.mark.asyncio
async def test_save_nonexistent_recipe(client):
    token = await _signup(client, "norecipe@test.com")
    resp = await client.post("/api/v1/recipes/nonexistent-id/save", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_saved_recipes(client):
    await _seed_recipe("saved-r2")  # conftest already has test-recipe-1
    token = await _signup(client, "listsaved@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    await client.post("/api/v1/recipes/saved-r2/save", headers={"Authorization": f"Bearer {token}"})
    resp = await client.get("/api/v1/me/saved", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_unsave_recipe(client):
    token = await _signup(client, "unsave@test.com")
    await client.post("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    resp = await client.delete("/api/v1/recipes/test-recipe-1/save", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"
    resp = await client.get("/api/v1/me/saved", headers={"Authorization": f"Bearer {token}"})
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_saved_requires_auth(client):
    resp = await client.get("/api/v1/me/saved")
    assert resp.status_code == 401


# ── Trending ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trending(client):
    # test-recipe-1 seeded by conftest
    resp = await client.get("/api/v1/trending?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert len(data["data"]) >= 1
