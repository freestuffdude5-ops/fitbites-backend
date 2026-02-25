"""Tests for recently viewed API — recipe browsing history."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_track_view(async_client: AsyncClient, auth_headers, test_recipe):
    """User can track viewing a recipe."""
    response = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/view",
        headers=auth_headers,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_track_view_invalid_recipe(async_client: AsyncClient, auth_headers):
    """Tracking view of non-existent recipe returns 404."""
    response = await async_client.post(
        "/api/v1/recipes/999999/view",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_track_view_idempotent(async_client: AsyncClient, auth_headers, test_recipe):
    """Tracking same recipe multiple times updates timestamp (idempotent)."""
    # View twice
    await async_client.post(f"/api/v1/recipes/{test_recipe['id']}/view", headers=auth_headers)
    await async_client.post(f"/api/v1/recipes/{test_recipe['id']}/view", headers=auth_headers)
    
    # Should only have one entry
    response = await async_client.get(
        f"/api/v1/users/{auth_headers['user_id']}/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["recipes"]) == 1


@pytest.mark.asyncio
async def test_get_recently_viewed_empty(async_client: AsyncClient, auth_headers):
    """Getting recently viewed with no history returns empty list."""
    # Get user_id from auth
    me_resp = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    
    response = await async_client.get(
        f"/api/v1/users/{user_id}/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recipes"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_recently_viewed_list(async_client: AsyncClient, auth_headers, test_recipe):
    """Getting recently viewed returns list of recipes with metadata."""
    # View recipe
    await async_client.post(f"/api/v1/recipes/{test_recipe['id']}/view", headers=auth_headers)
    
    # Get user_id
    me_resp = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    
    # Get history
    response = await async_client.get(
        f"/api/v1/users/{user_id}/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["recipes"]) == 1
    recipe = data["recipes"][0]
    assert recipe["id"] == test_recipe["id"]
    assert recipe["title"] == test_recipe["title"]
    assert "viewed_at" in recipe


@pytest.mark.asyncio
async def test_get_recently_viewed_ordered(async_client: AsyncClient, auth_headers, test_recipes):
    """Recently viewed list is ordered by view time (newest first)."""
    # View 3 recipes in order
    for recipe in test_recipes[:3]:
        await async_client.post(f"/api/v1/recipes/{recipe['id']}/view", headers=auth_headers)
    
    # Get history
    me_resp = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    response = await async_client.get(
        f"/api/v1/users/{user_id}/recently-viewed",
        headers=auth_headers,
    )
    
    data = response.json()
    assert len(data["recipes"]) == 3
    # Most recent first
    assert data["recipes"][0]["id"] == test_recipes[2]["id"]


@pytest.mark.asyncio
async def test_get_recently_viewed_limit(async_client: AsyncClient, auth_headers, test_recipes):
    """Recently viewed respects limit parameter."""
    # View 5 recipes
    for recipe in test_recipes[:5]:
        await async_client.post(f"/api/v1/recipes/{recipe['id']}/view", headers=auth_headers)
    
    # Get history with limit
    me_resp = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    response = await async_client.get(
        f"/api/v1/users/{user_id}/recently-viewed?limit=3",
        headers=auth_headers,
    )
    
    data = response.json()
    assert len(data["recipes"]) == 3


@pytest.mark.asyncio
async def test_get_recently_viewed_wrong_user(async_client: AsyncClient, auth_headers):
    """User cannot view other users' history."""
    response = await async_client.get(
        "/api/v1/users/999999/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_clear_history(async_client: AsyncClient, auth_headers, test_recipe):
    """User can clear their recently viewed history."""
    # View recipe
    await async_client.post(f"/api/v1/recipes/{test_recipe['id']}/view", headers=auth_headers)
    
    # Get user_id
    me_resp = await async_client.get("/api/v1/me", headers=auth_headers)
    user_id = me_resp.json()["id"]
    
    # Clear history
    response = await async_client.delete(
        f"/api/v1/users/{user_id}/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 204
    
    # Verify cleared
    get_resp = await async_client.get(
        f"/api/v1/users/{user_id}/recently-viewed",
        headers=auth_headers,
    )
    assert len(get_resp.json()["recipes"]) == 0


@pytest.mark.asyncio
async def test_clear_history_wrong_user(async_client: AsyncClient, auth_headers):
    """User cannot clear other users' history."""
    response = await async_client.delete(
        "/api/v1/users/999999/recently-viewed",
        headers=auth_headers,
    )
    assert response.status_code == 403
