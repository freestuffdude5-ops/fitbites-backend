"""Tests for ATLAS's user favorites + grocery list features."""
from __future__ import annotations

import pytest

# Seed recipe from conftest
RECIPE_ID = "test-recipe-1"


async def _register(client, device_id="atlas-test-001"):
    resp = await client.post("/api/v1/users/register", json={"device_id": device_id})
    assert resp.status_code == 201
    return resp.json()["id"]


# ── User Registration (device-based) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_anonymous_user(client):
    resp = await client.post("/api/v1/users/register", json={"device_id": "atlas-device-123"})
    assert resp.status_code == 201
    assert resp.json()["device_id"] == "atlas-device-123"
    assert resp.json()["id"]


@pytest.mark.asyncio
async def test_register_email_user(client):
    resp = await client.post("/api/v1/users/register", json={
        "email": "atlas@fitbites.app", "display_name": "Atlas Test",
    })
    assert resp.status_code == 201
    assert resp.json()["email"] == "atlas@fitbites.app"


@pytest.mark.asyncio
async def test_register_idempotent(client):
    r1 = await client.post("/api/v1/users/register", json={"device_id": "atlas-dupe"})
    r2 = await client.post("/api/v1/users/register", json={"device_id": "atlas-dupe"})
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_register_requires_id(client):
    assert (await client.post("/api/v1/users/register", json={})).status_code == 400


@pytest.mark.asyncio
async def test_update_preferences(client):
    uid = await _register(client, "pref-dev")
    resp = await client.patch(f"/api/v1/users/{uid}/preferences", json={
        "dietary": ["keto"], "max_calories": 500,
    })
    assert resp.status_code == 200
    assert resp.json()["preferences"]["max_calories"] == 500


# ── Saved Recipes ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_list_recipe(client):
    uid = await _register(client, "save-dev")
    # Save
    resp = await client.post(f"/api/v1/users/{uid}/saved", json={
        "recipe_id": RECIPE_ID, "collection": "Meal Prep",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "saved"
    # List
    resp = await client.get(f"/api/v1/users/{uid}/saved")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1
    assert resp.json()["data"][0]["recipe"]["id"] == RECIPE_ID


@pytest.mark.asyncio
async def test_collections(client):
    uid = await _register(client, "coll-dev")
    await client.post(f"/api/v1/users/{uid}/saved", json={
        "recipe_id": RECIPE_ID, "collection": "Breakfast",
    })
    resp = await client.get(f"/api/v1/users/{uid}/collections")
    assert any(c["name"] == "Breakfast" for c in resp.json()["collections"])


@pytest.mark.asyncio
async def test_unsave_recipe(client):
    uid = await _register(client, "unsave-dev")
    await client.post(f"/api/v1/users/{uid}/saved", json={"recipe_id": RECIPE_ID})
    assert (await client.delete(f"/api/v1/users/{uid}/saved/{RECIPE_ID}")).status_code == 204
    assert len((await client.get(f"/api/v1/users/{uid}/saved")).json()["data"]) == 0


# ── Grocery Lists ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_grocery_list_with_affiliates(client):
    uid = await _register(client, "gl-dev")
    resp = await client.post(f"/api/v1/users/{uid}/grocery-lists", json={
        "name": "This Week", "recipe_ids": [RECIPE_ID],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["item_count"] > 0
    assert data["shop_all"]["provider"] == "instacart"
    for item in data["items"]:
        assert "affiliate" in item


@pytest.mark.asyncio
async def test_check_grocery_item(client):
    uid = await _register(client, "check-dev")
    create = await client.post(f"/api/v1/users/{uid}/grocery-lists", json={
        "name": "Check", "recipe_ids": [RECIPE_ID],
    })
    list_id = create.json()["id"]
    resp = await client.patch(f"/api/v1/users/{uid}/grocery-lists/{list_id}/check", json={
        "index": 0, "checked": True,
    })
    assert resp.status_code == 200
    assert resp.json()["item"]["checked"] is True


@pytest.mark.asyncio
async def test_grocery_list_crud(client):
    uid = await _register(client, "crud-dev")
    # Create
    create = await client.post(f"/api/v1/users/{uid}/grocery-lists", json={
        "name": "Delete Me", "recipe_ids": [RECIPE_ID],
    })
    list_id = create.json()["id"]
    # List
    resp = await client.get(f"/api/v1/users/{uid}/grocery-lists")
    assert len(resp.json()["data"]) == 1
    # Get
    resp = await client.get(f"/api/v1/users/{uid}/grocery-lists/{list_id}")
    assert resp.json()["shop_all"] is not None
    # Delete
    assert (await client.delete(f"/api/v1/users/{uid}/grocery-lists/{list_id}")).status_code == 204
