"""Tests for recipe sharing API."""
import pytest


@pytest.mark.asyncio
async def test_get_share_link(client):
    r = await client.get("/api/v1/recipes/test-recipe-1/share")
    assert r.status_code == 200
    data = r.json()
    assert "fitbites.io" in data["share_url"]
    assert data["recipe_id"] == "test-recipe-1"
    assert data["title"] == "Test Chicken Bowl"
    assert len(data["description"]) > 0


@pytest.mark.asyncio
async def test_share_link_nonexistent(client):
    r = await client.get("/api/v1/recipes/nonexistent/share")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_page_renders_og(client):
    # First get the share link to find short_id
    r = await client.get("/api/v1/recipes/test-recipe-1/share")
    share_url = r.json()["share_url"]
    short_id = share_url.split("/r/")[-1]

    # Access the share page
    r = await client.get(f"/api/v1/r/{short_id}")
    assert r.status_code == 200
    html = r.text
    assert "og:title" in html
    assert "Test Chicken Bowl" in html
    assert "og:description" in html
    assert "twitter:card" in html


@pytest.mark.asyncio
async def test_share_page_404_unknown(client):
    r = await client.get("/api/v1/r/00000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_includes_nutrition(client):
    r = await client.get("/api/v1/recipes/test-recipe-1/share")
    data = r.json()
    assert "cal" in data["description"] or "protein" in data["description"]
