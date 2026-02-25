"""Tests for Collections API — premium recipe organization."""
import pytest


@pytest.fixture
async def auth(client):
    """Create user and return (headers, user_id)."""
    resp = await client.post("/api/v1/auth/signup", json={
        "email": "collector@test.com", "password": "pass1234", "display_name": "Collector"
    })
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]


@pytest.fixture
async def collection(client, auth):
    """Create a collection and return its data."""
    headers, _ = auth
    resp = await client.post("/api/v1/collections", headers=headers, json={
        "name": "Weeknight Dinners", "emoji": "🍝", "description": "Quick easy meals"
    })
    return resp.json()


# ── CRUD ─────────────────────────────────────────────────────────────────

async def test_create_collection(client, auth):
    headers, _ = auth
    resp = await client.post("/api/v1/collections", headers=headers, json={
        "name": "Test Collection", "emoji": "🔥"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Collection"
    assert data["emoji"] == "🔥"
    assert data["recipe_count"] == 0
    assert data["is_public"] is False


async def test_create_duplicate_name_rejected(client, auth, collection):
    headers, _ = auth
    resp = await client.post("/api/v1/collections", headers=headers, json={
        "name": "Weeknight Dinners"
    })
    assert resp.status_code == 409


async def test_list_collections(client, auth, collection):
    headers, _ = auth
    resp = await client.get("/api/v1/collections", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(c["name"] == "Weeknight Dinners" for c in data["collections"])


async def test_get_collection_detail(client, auth, collection):
    headers, _ = auth
    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Weeknight Dinners"
    assert "recipes" in data


async def test_update_collection(client, auth, collection):
    headers, _ = auth
    resp = await client.patch(f"/api/v1/collections/{collection['id']}", headers=headers, json={
        "name": "Updated Name", "emoji": "🥗"
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["emoji"] == "🥗"


async def test_delete_collection(client, auth, collection):
    headers, _ = auth
    resp = await client.delete(f"/api/v1/collections/{collection['id']}", headers=headers)
    assert resp.status_code == 204

    # Verify gone
    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=headers)
    assert resp.status_code == 404


# ── Recipe Management ────────────────────────────────────────────────────

async def test_add_recipe_to_collection(client, auth, collection):
    headers, _ = auth
    resp = await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1", "notes": "Love this one!"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["recipe_id"] == "test-recipe-1"
    assert data["notes"] == "Love this one!"


async def test_add_duplicate_recipe_rejected(client, auth, collection):
    headers, _ = auth
    await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1"
    })
    resp = await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1"
    })
    assert resp.status_code == 409


async def test_add_nonexistent_recipe(client, auth, collection):
    headers, _ = auth
    resp = await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "does-not-exist"
    })
    assert resp.status_code == 404


async def test_remove_recipe_from_collection(client, auth, collection):
    headers, _ = auth
    await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1"
    })
    resp = await client.delete(f"/api/v1/collections/{collection['id']}/recipes/test-recipe-1", headers=headers)
    assert resp.status_code == 204


async def test_collection_recipe_count_updates(client, auth, collection):
    headers, _ = auth
    await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1"
    })
    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=headers)
    assert resp.json()["recipe_count"] == 1

    await client.delete(f"/api/v1/collections/{collection['id']}/recipes/test-recipe-1", headers=headers)
    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=headers)
    assert resp.json()["recipe_count"] == 0


async def test_collection_detail_includes_recipe_data(client, auth, collection):
    headers, _ = auth
    await client.post(f"/api/v1/collections/{collection['id']}/recipes", headers=headers, json={
        "recipe_id": "test-recipe-1"
    })
    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=headers)
    data = resp.json()
    assert len(data["recipes"]) == 1
    recipe = data["recipes"][0]
    assert recipe["title"] == "Test Chicken Bowl"
    assert recipe["calories"] == 400
    assert recipe["protein_g"] == 35


# ── Reordering ───────────────────────────────────────────────────────────

async def test_reorder_collections(client, auth):
    headers, _ = auth
    r1 = (await client.post("/api/v1/collections", headers=headers, json={"name": "First"})).json()
    r2 = (await client.post("/api/v1/collections", headers=headers, json={"name": "Second"})).json()

    resp = await client.post("/api/v1/collections/reorder", headers=headers, json={
        "ordered_ids": [r2["id"], r1["id"]]
    })
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


# ── Public Collections ──────────────────────────────────────────────────

async def test_public_collection_accessible(client, auth, collection):
    headers, _ = auth
    # Make public
    await client.patch(f"/api/v1/collections/{collection['id']}", headers=headers, json={
        "is_public": True
    })
    # Access without auth
    resp = await client.get(f"/api/v1/collections/{collection['id']}/public")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Weeknight Dinners"


async def test_private_collection_not_accessible_publicly(client, auth, collection):
    resp = await client.get(f"/api/v1/collections/{collection['id']}/public")
    assert resp.status_code == 404


# ── Authorization ────────────────────────────────────────────────────────

async def test_cannot_access_other_users_collection(client, auth, collection):
    # Create second user
    resp = await client.post("/api/v1/auth/signup", json={
        "email": "other@test.com", "password": "pass1234", "display_name": "Other"
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.get(f"/api/v1/collections/{collection['id']}", headers=other_headers)
    assert resp.status_code == 404


async def test_unauthenticated_rejected(client):
    resp = await client.get("/api/v1/collections")
    assert resp.status_code == 401
