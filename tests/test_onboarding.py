"""Tests for onboarding & dietary preferences API."""
import pytest


@pytest.fixture
async def auth(client):
    resp = await client.post("/api/v1/auth/signup", json={
        "email": "onboard@test.com", "password": "pass1234", "display_name": "New User"
    })
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


# ── Options (no auth) ───────────────────────────────────────────────────

async def test_get_onboarding_options(client):
    resp = await client.get("/api/v1/onboarding/options")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["goals"]) == 4
    assert len(data["dietary_restrictions"]) >= 8
    assert len(data["allergens"]) >= 8
    assert all("emoji" in g for g in data["goals"])


# ── Quick Setup ──────────────────────────────────────────────────────────

async def test_quick_setup(client, auth):
    resp = await client.post("/api/v1/onboarding/quick-setup", headers=auth, json={
        "goal": "lose_weight",
        "weight_kg": 80, "height_cm": 178, "age": 28,
        "sex": "male", "activity_level": "moderate",
        "dietary_restrictions": ["gluten_free"]
    })
    assert resp.status_code == 200
    data = resp.json()
    targets = data["targets"]
    assert targets["target_calories"] > 1200
    assert targets["target_protein_g"] >= 140
    assert data["preferences"]["onboarding_completed"] is True
    assert data["preferences"]["goal"] == "lose_weight"


async def test_calculate_targets_no_auth(client):
    resp = await client.post("/api/v1/onboarding/calculate-targets", json={
        "goal": "build_muscle",
        "weight_kg": 70, "height_cm": 170, "age": 25,
        "sex": "female", "activity_level": "active",
    })
    assert resp.status_code == 200
    targets = resp.json()["targets"]
    assert targets["target_protein_g"] >= 140
    assert targets["tdee"] > 0
    assert targets["bmr"] > 0


async def test_male_vs_female_bmr_difference(client):
    base = {"goal": "maintain", "weight_kg": 70, "height_cm": 170, "age": 25, "activity_level": "moderate"}
    male = await client.post("/api/v1/onboarding/calculate-targets", json={**base, "sex": "male"})
    female = await client.post("/api/v1/onboarding/calculate-targets", json={**base, "sex": "female"})
    assert male.json()["targets"]["tdee"] > female.json()["targets"]["tdee"]


# ── Profile CRUD ─────────────────────────────────────────────────────────

async def test_set_profile(client, auth):
    resp = await client.post("/api/v1/onboarding/profile", headers=auth, json={
        "goal": "eat_healthier",
        "dietary_restrictions": ["vegetarian", "dairy_free"],
        "allergens": ["peanuts"],
        "skill_level": "intermediate",
        "max_cook_time_minutes": 30,
    })
    assert resp.status_code == 200
    prefs = resp.json()["preferences"]
    assert prefs["goal"] == "eat_healthier"
    assert "vegetarian" in prefs["dietary_restrictions"]
    assert prefs["skill_level"] == "intermediate"


async def test_partial_update(client, auth):
    await client.post("/api/v1/onboarding/profile", headers=auth, json={
        "goal": "lose_weight", "skill_level": "beginner"
    })
    resp = await client.post("/api/v1/onboarding/profile", headers=auth, json={
        "target_calories": 1800
    })
    prefs = resp.json()["preferences"]
    assert prefs["goal"] == "lose_weight"
    assert prefs["target_calories"] == 1800


async def test_get_profile(client, auth):
    await client.post("/api/v1/onboarding/profile", headers=auth, json={"goal": "maintain"})
    resp = await client.get("/api/v1/onboarding/profile", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["onboarding_completed"] is True


async def test_profile_not_completed_initially(client, auth):
    resp = await client.get("/api/v1/onboarding/profile", headers=auth)
    assert resp.json()["onboarding_completed"] is False


# ── Validation ───────────────────────────────────────────────────────────

async def test_invalid_goal(client, auth):
    resp = await client.post("/api/v1/onboarding/profile", headers=auth, json={
        "goal": "fly_to_moon"
    })
    assert resp.status_code == 422


async def test_calories_range(client, auth):
    resp = await client.post("/api/v1/onboarding/profile", headers=auth, json={
        "target_calories": 100
    })
    assert resp.status_code == 422


async def test_requires_auth(client):
    resp = await client.post("/api/v1/onboarding/profile", json={"goal": "maintain"})
    assert resp.status_code == 401
