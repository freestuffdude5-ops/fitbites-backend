"""Tests for onboarding & dietary preferences API."""
import pytest


@pytest.mark.asyncio
async def test_onboarding_options_no_auth(client):
    """Options endpoint should work without auth."""
    r = await client.get("/api/v1/onboarding/options")
    assert r.status_code == 200
    data = r.json()
    assert len(data["goals"]) == 4
    assert len(data["dietary_restrictions"]) == 10
    assert len(data["allergens"]) == 9
    assert len(data["skill_levels"]) == 3
    assert len(data["activity_levels"]) == 5
    # Check structure
    assert data["goals"][0]["id"] == "lose_weight"
    assert "emoji" in data["goals"][0]


@pytest.mark.asyncio
async def test_calculate_targets_no_auth(client):
    """Preview targets should work without auth."""
    r = await client.post("/api/v1/onboarding/calculate-targets", json={
        "goal": "build_muscle",
        "weight_kg": 80, "height_cm": 180, "age": 28,
        "sex": "male", "activity_level": "active",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["goal"] == "build_muscle"
    assert data["targets"]["target_calories"] > 2000
    assert data["targets"]["target_protein_g"] >= 150  # 80kg * 2.2
    assert "tdee" in data["targets"]
    assert "bmr" in data["targets"]


@pytest.mark.asyncio
async def test_set_profile_requires_auth(client):
    """Profile endpoint requires auth."""
    r = await client.post("/api/v1/onboarding/profile", json={"goal": "lose_weight"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_set_profile(client, auth_headers):
    """Set onboarding profile with auth."""
    headers = {k: v for k, v in auth_headers.items() if k == "Authorization"}
    r = await client.post("/api/v1/onboarding/profile", json={
        "goal": "lose_weight",
        "dietary_restrictions": ["vegetarian", "gluten_free"],
        "allergens": ["peanuts"],
        "skill_level": "intermediate",
        "max_cook_time_minutes": 30,
        "target_calories": 2000,
        "target_protein_g": 150,
    }, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["preferences"]["goal"] == "lose_weight"
    assert data["preferences"]["onboarding_completed"] is True
    assert "vegetarian" in data["preferences"]["dietary_restrictions"]


@pytest.mark.asyncio
async def test_get_profile(client, auth_headers):
    """Get onboarding profile."""
    headers = {k: v for k, v in auth_headers.items() if k == "Authorization"}
    # Initially not completed
    r = await client.get("/api/v1/onboarding/profile", headers=headers)
    assert r.status_code == 200
    assert r.json()["onboarding_completed"] is False


@pytest.mark.asyncio
async def test_quick_setup(client, auth_headers):
    """Quick setup auto-calculates targets."""
    headers = {k: v for k, v in auth_headers.items() if k == "Authorization"}
    r = await client.post("/api/v1/onboarding/quick-setup", json={
        "goal": "lose_weight",
        "weight_kg": 70, "height_cm": 165, "age": 30,
        "sex": "female", "activity_level": "moderate",
        "dietary_restrictions": ["keto"],
    }, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["targets"]["target_calories"] >= 1200
    assert data["preferences"]["onboarding_completed"] is True
    assert data["preferences"]["body_stats"]["weight_kg"] == 70


@pytest.mark.asyncio
async def test_partial_update(client, auth_headers):
    """Partial update preserves existing preferences."""
    headers = {k: v for k, v in auth_headers.items() if k == "Authorization"}
    # Set goal
    await client.post("/api/v1/onboarding/profile", json={"goal": "build_muscle"}, headers=headers)
    # Update only skill level (goal should persist)
    r = await client.post("/api/v1/onboarding/profile", json={"skill_level": "advanced"}, headers=headers)
    assert r.status_code == 200
    prefs = r.json()["preferences"]
    assert prefs["goal"] == "build_muscle"
    assert prefs["skill_level"] == "advanced"


@pytest.mark.asyncio
async def test_calculate_targets_validation(client):
    """Invalid body stats should be rejected."""
    r = await client.post("/api/v1/onboarding/calculate-targets", json={
        "goal": "lose_weight",
        "weight_kg": 5,  # too low (min 30)
        "height_cm": 180, "age": 28,
        "sex": "male", "activity_level": "active",
    })
    assert r.status_code == 422
