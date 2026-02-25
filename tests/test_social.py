"""Tests for social features: follows, activity feed, shares, profiles."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from httpx import AsyncClient, ASGITransport

def _mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()
    return session


def _mock_user(user_id="user-1", email="test@test.com", display_name="Test User"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.display_name = display_name
    user.avatar_url = None
    user.preferences = {}
    user.created_at = datetime.now(timezone.utc)
    return user


@pytest.fixture
def app():
    from src.api.main import app as _app
    return _app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Follow Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_follow_user(client, app):
    """Test following another user."""
    mock_user = _mock_user("user-1")
    target_user = _mock_user("user-2", "target@test.com", "Target")

    mock_session = _mock_session()

    # Mock: target user exists, not already following
    result_target = MagicMock()
    result_target.scalar_one_or_none.return_value = target_user

    result_existing = MagicMock()
    result_existing.scalar_one_or_none.return_value = None

    mock_session.execute = AsyncMock(side_effect=[result_target, result_existing])

    with patch("src.api.social.require_user", return_value=mock_user), \
         patch("src.api.social.get_session", return_value=mock_session):
        app.dependency_overrides[__import__("src.auth", fromlist=["require_user"]).require_user] = lambda: mock_user
        app.dependency_overrides[__import__("src.db.engine", fromlist=["get_session"]).get_session] = lambda: mock_session

        resp = await client.post("/api/v1/users/follow", json={"user_id": "user-2"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "following"
    # Should have added follow + activity
    assert mock_session.add.call_count == 2


@pytest.mark.asyncio
async def test_cannot_follow_self(client, app):
    """Test that following yourself returns 400."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.post("/api/v1/users/follow", json={"user_id": "user-1"})
    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_follow_nonexistent_user(client, app):
    """Test following a nonexistent user returns 404."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    result_target = MagicMock()
    result_target.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result_target)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.post("/api/v1/users/follow", json={"user_id": "ghost-user"})
    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_already_following(client, app):
    """Test idempotent follow returns already_following."""
    mock_user = _mock_user("user-1")
    target_user = _mock_user("user-2")
    existing_follow = MagicMock()

    mock_session = _mock_session()

    result_target = MagicMock()
    result_target.scalar_one_or_none.return_value = target_user
    result_existing = MagicMock()
    result_existing.scalar_one_or_none.return_value = existing_follow

    mock_session.execute = AsyncMock(side_effect=[result_target, result_existing])

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.post("/api/v1/users/follow", json={"user_id": "user-2"})
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_following"


@pytest.mark.asyncio
async def test_unfollow_user(client, app):
    """Test unfollowing a user."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    result = MagicMock()
    result.rowcount = 1
    mock_session.execute = AsyncMock(return_value=result)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.request("DELETE", "/api/v1/users/follow", json={"user_id": "user-2"})
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "unfollowed"


@pytest.mark.asyncio
async def test_unfollow_not_following(client, app):
    """Test unfollowing someone you don't follow."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    result = MagicMock()
    result.rowcount = 0
    mock_session.execute = AsyncMock(return_value=result)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.request("DELETE", "/api/v1/users/follow", json={"user_id": "user-2"})
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_following"


# ── Share Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_recipe(client, app):
    """Test creating a share link."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    recipe_result = MagicMock()
    recipe_result.scalar_one_or_none.return_value = MagicMock()
    mock_session.execute = AsyncMock(return_value=recipe_result)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.post(
        "/api/v1/recipes/recipe-123/share",
        json={"platform": "instagram"},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "share_code" in data
    assert "share_url" in data
    assert data["recipe_id"] == "recipe-123"


@pytest.mark.asyncio
async def test_share_nonexistent_recipe(client, app):
    """Test sharing a nonexistent recipe returns 404."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    recipe_result = MagicMock()
    recipe_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=recipe_result)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.post("/api/v1/recipes/nonexistent/share", json={})
    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resolve_share(client, app):
    """Test resolving a share code."""
    mock_session = _mock_session()

    share = MagicMock()
    share.recipe_id = "recipe-123"
    share.user_id = "user-1"
    share.clicks = "5"

    result = MagicMock()
    result.scalar_one_or_none.return_value = share
    mock_session.execute = AsyncMock(return_value=result)

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/s/abc123")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["recipe_id"] == "recipe-123"
    assert data["clicks"] == 6  # incremented


@pytest.mark.asyncio
async def test_resolve_invalid_share(client, app):
    """Test resolving an invalid share code returns 404."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=result)

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/s/invalid-code")
    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ── Activity Feed Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_activity_feed(client, app):
    """Test activity feed when not following anyone."""
    mock_user = _mock_user("user-1")
    mock_session = _mock_session()

    # No following
    following_result = MagicMock()
    following_result.fetchall.return_value = []
    mock_session.execute = AsyncMock(return_value=following_result)

    from src.auth import require_user
    from src.db.engine import get_session

    app.dependency_overrides[require_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/feed/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []


# ── Followers/Following List Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_followers(client, app):
    """Test listing followers."""
    mock_session = _mock_session()

    follower = _mock_user("follower-1", "f@test.com", "Follower")
    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = [follower]

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    mock_session.execute = AsyncMock(side_effect=[users_result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/users/user-1/followers")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) == 1
    assert data["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_get_following(client, app):
    """Test listing who a user follows."""
    mock_session = _mock_session()

    following = _mock_user("following-1", "f@test.com", "Following")
    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = [following]

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    mock_session.execute = AsyncMock(side_effect=[users_result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/users/user-1/following")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) == 1
    assert data["pagination"]["total"] == 1
