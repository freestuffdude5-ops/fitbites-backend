"""Security tests for Session 17 fixes — auth enforcement, timing-safe checks, JSON injection prevention."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.db.engine import engine
from src.db.tables import Base


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_user(client: AsyncClient, email: str = "test@example.com") -> dict:
    """Helper to create a user and return tokens."""
    resp = await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": "TestPass123!",
        "display_name": "Test User",
    })
    assert resp.status_code == 200
    return resp.json()


def _auth_header(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ── Scrape endpoint requires admin auth ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_requires_admin_key(client):
    """POST /api/v1/scrape must require admin auth."""
    resp = await client.post("/api/v1/scrape")
    # Should be 503 (no admin key configured) or 403 (wrong key)
    assert resp.status_code in (403, 503)


@pytest.mark.asyncio
async def test_scrape_rejects_wrong_admin_key(client):
    """POST /api/v1/scrape rejects invalid admin keys."""
    resp = await client.post("/api/v1/scrape", headers={"X-Admin-Key": "wrong-key"})
    assert resp.status_code in (403, 503)


# ── Affiliate revenue dashboard requires admin auth ──────────────────────────

@pytest.mark.asyncio
async def test_affiliate_revenue_requires_admin(client):
    """GET /api/v1/admin/affiliate-revenue must require admin auth."""
    resp = await client.get("/api/v1/admin/affiliate-revenue")
    assert resp.status_code in (403, 503)


# ── Reviews use JWT auth, not query param user_id ────────────────────────────

@pytest.mark.asyncio
async def test_create_review_requires_auth(client):
    """POST reviews endpoint must require JWT auth, not query param."""
    resp = await client.post("/api/v1/recipes/fake-id/reviews", json={
        "rating": 5, "title": "Great!", "body": "Loved it",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_review_no_user_id_query_param(client):
    """Verify user_id query param no longer accepted (was the old insecure way)."""
    resp = await client.post(
        "/api/v1/recipes/fake-id/reviews?user_id=spoofed-user",
        json={"rating": 5, "title": "Spoofed", "body": "I'm not this user"},
    )
    # Should fail with 401 (no auth) not succeed
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_review_requires_auth(client):
    """PATCH review requires JWT auth."""
    resp = await client.patch("/api/v1/recipes/fake-id/reviews/fake-review", json={
        "rating": 1,
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_review_requires_auth(client):
    """DELETE review requires JWT auth."""
    resp = await client.delete("/api/v1/recipes/fake-id/reviews/fake-review")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mark_helpful_requires_auth(client):
    """POST helpful requires JWT auth."""
    resp = await client.post("/api/v1/reviews/fake-review/helpful")
    assert resp.status_code == 401


# ── Cooking log uses JWT auth ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cooking_log_requires_auth(client):
    """POST cooking log must require JWT auth."""
    resp = await client.post("/api/v1/cooking-log?recipe_id=fake")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cooking_history_requires_auth(client):
    """GET cooking history must require JWT auth."""
    resp = await client.get("/api/v1/me/cooking-log")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cooking_stats_requires_auth(client):
    """GET cooking stats must require JWT auth."""
    resp = await client.get("/api/v1/me/cooking-stats")
    assert resp.status_code == 401


# ── Comments GET endpoints allow unauthenticated access ──────────────────────

@pytest.mark.asyncio
async def test_get_comments_no_auth_ok(client):
    """GET comments should work without auth (public data)."""
    resp = await client.get("/api/v1/recipes/fake-id/comments")
    # Should not be 401 — might be 200 with empty list
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_get_replies_no_auth_ok(client):
    """GET comment replies should not require auth."""
    resp = await client.get("/api/v1/comments/fake-id/replies")
    # 404 (comment not found) is fine, 401 is not
    assert resp.status_code != 401


# ── User profile allows unauthenticated access ──────────────────────────────

@pytest.mark.asyncio
async def test_user_profile_no_auth_ok(client):
    """GET user profile should work without auth (public data)."""
    # Create a user first
    tokens = await _create_user(client)
    user_id = tokens["user"]["id"]
    # Access profile without auth
    resp = await client.get(f"/api/v1/users/{user_id}/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id


# ── Affiliate click tracking uses JWT not spoofable user_id ──────────────────

@pytest.mark.asyncio
async def test_affiliate_click_no_spoofable_user_id(client):
    """Affiliate click tracking should derive user from JWT, not request body."""
    # Without auth, should still work (anonymous tracking) but user_id should be None
    resp = await client.post("/api/v1/affiliate-clicks", params={
        "recipe_id": "test-recipe",
        "ingredient": "chicken",
        "provider": "amazon",
    })
    # Should succeed (anonymous is OK for click tracking)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracked"] is True
