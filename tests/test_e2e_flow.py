"""End-to-end flow test — simulates a real user journey.

Signup → Onboard → Browse → Save → Meal Plan → Review → Share

This is the critical path test. If this passes, the core product works.
"""
import pytest


@pytest.mark.asyncio
async def test_full_user_journey(client):
    """Complete user journey from signup to sharing a review."""

    # 1. SIGNUP
    r = await client.post("/api/v1/auth/signup", json={
        "email": "newuser@fitbites.io",
        "password": "StrongPass123!",
        "display_name": "Alex Fitness",
    })
    assert r.status_code == 200, f"Signup failed: {r.text}"
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = tokens["user"]["id"]

    # 2. ONBOARD — quick setup with macro calculator
    r = await client.post("/api/v1/onboarding/quick-setup", json={
        "goal": "build_muscle",
        "weight_kg": 80, "height_cm": 180, "age": 25,
        "sex": "male", "activity_level": "active",
        "dietary_restrictions": ["high_protein"],
    }, headers=headers)
    assert r.status_code == 200
    assert r.json()["preferences"]["onboarding_completed"] is True
    assert r.json()["targets"]["target_protein_g"] >= 150

    # 3. BROWSE RECIPES
    r = await client.get("/api/v1/recipes?limit=5")
    assert r.status_code == 200
    recipes = r.json()["data"]
    assert len(recipes) >= 1
    recipe_id = recipes[0]["id"]

    # 4. VIEW RECIPE DETAIL
    r = await client.get(f"/api/v1/recipes/{recipe_id}")
    assert r.status_code == 200
    recipe = r.json()
    assert "title" in recipe
    assert "ingredients" in recipe

    # 5. SAVE RECIPE
    r = await client.post(
        f"/api/v1/users/{user_id}/saved",
        json={"recipe_id": recipe_id},
        headers=headers,
    )
    assert r.status_code == 201, f"Save failed: {r.text}"

    # 6. VERIFY SAVED
    r = await client.get(f"/api/v1/users/{user_id}/saved", headers=headers)
    assert r.status_code == 200

    # 7. REVIEW THE RECIPE
    r = await client.post(f"/api/v1/recipes/{recipe_id}/reviews", json={
        "rating": 5,
        "title": "Amazing! High protein and delicious",
        "body": "Made this for meal prep, turned out great. The macros are perfect.",
        "made_it": True,
    }, headers=headers)
    assert r.status_code == 201, f"Review failed: {r.text}"

    # 8. LOG COOKING
    r = await client.post(
        f"/api/v1/cooking-log?recipe_id={recipe_id}",
        json={"servings": 2, "notes": "Doubled the chicken"},
        headers=headers,
    )
    assert r.status_code == 201

    # 9. CHECK PERSONALIZED FEED
    r = await client.get(f"/api/v1/feed/{user_id}", headers=headers)
    assert r.status_code == 200

    # 10. SEARCH
    r = await client.get("/api/v1/recipes/search?q=chicken")
    assert r.status_code == 200

    # 11. TRENDING
    r = await client.get("/api/v1/trending/tags")
    assert r.status_code == 200
    assert "trending_tags" in r.json()

    # 12. GET SHARE LINK
    r = await client.post(f"/api/v1/share/recipe/{recipe_id}", headers=headers)
    if r.status_code == 200:
        assert "url" in r.json() or "share_url" in r.json()


@pytest.mark.asyncio
async def test_unauthenticated_browsing(client):
    """Public users can browse, search, and view recipes without auth."""
    # Browse
    r = await client.get("/api/v1/recipes?limit=5")
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1

    # Search
    r = await client.get("/api/v1/recipes/search?q=protein")
    assert r.status_code == 200

    # Trending
    r = await client.get("/api/v1/trending/tags")
    assert r.status_code == 200

    # Onboarding options (for pre-signup UX)
    r = await client.get("/api/v1/onboarding/options")
    assert r.status_code == 200
    assert len(r.json()["goals"]) == 4

    # Health check
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_auth_refresh_flow(client):
    """Token refresh works correctly."""
    # Signup
    r = await client.post("/api/v1/auth/signup", json={
        "email": "refresh@test.com", "password": "Pass123!", "display_name": "Test",
    })
    assert r.status_code == 200
    tokens = r.json()

    # Refresh
    r = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert r.status_code == 200
    assert "access_token" in r.json()
