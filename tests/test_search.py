"""Tests for advanced search & discovery API."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone


def _mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


def _mock_recipe_row(
    recipe_id="r1",
    title="Chicken Bowl",
    calories=350,
    protein=40.0,
    carbs=20.0,
    fat=10.0,
    cook_time=15,
    difficulty="easy",
    tags=None,
    virality_score=85.0,
):
    row = MagicMock()
    row.id = recipe_id
    row.title = title
    row.description = f"A delicious {title}"
    row.creator_username = "chef"
    row.creator_display_name = "Chef"
    from src.models import Platform
    row.creator_platform = Platform.YOUTUBE
    row.creator_profile_url = "https://youtube.com/@chef"
    row.creator_avatar_url = None
    row.creator_follower_count = 1000
    row.platform = Platform.YOUTUBE
    row.source_url = f"https://youtube.com/{recipe_id}"
    row.thumbnail_url = None
    row.video_url = None
    row.ingredients = [{"name": "chicken", "quantity": "200g"}]
    row.steps = ["Cook it"]
    row.tags = tags or ["high-protein"]
    row.calories = calories
    row.protein_g = protein
    row.carbs_g = carbs
    row.fat_g = fat
    row.fiber_g = 5.0
    row.sugar_g = 2.0
    row.servings = 1
    row.views = 10000
    row.likes = 500
    row.comments = 50
    row.shares = 100
    row.cook_time_minutes = cook_time
    row.difficulty = difficulty
    row.virality_score = virality_score
    row.scraped_at = datetime.now(timezone.utc)
    row.published_at = None
    return row


@pytest.fixture
def app():
    from src.api.main import app as _app
    return _app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_discover_no_filters(client, app):
    """Test discover endpoint with no filters returns all recipes."""
    mock_session = _mock_session()
    recipe = _mock_recipe_row()

    result = MagicMock()
    result.scalars.return_value.all.return_value = [recipe]
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["data"]) == 1
    assert data["facets"]["filters_applied"] == 0
    assert data["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_discover_with_text_search(client, app):
    """Test discover with text query."""
    mock_session = _mock_session()
    recipe = _mock_recipe_row(title="Grilled Chicken")

    result = MagicMock()
    result.scalars.return_value.all.return_value = [recipe]
    count_result = MagicMock()
    count_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover?q=chicken")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["facets"]["filters_applied"] == 1


@pytest.mark.asyncio
async def test_discover_with_macro_filters(client, app):
    """Test discover with calorie + protein filters."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get(
        "/api/v1/discover?max_calories=400&min_protein=30"
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["facets"]["filters_applied"] == 2


@pytest.mark.asyncio
async def test_discover_with_cook_time(client, app):
    """Test discover with cook time filter."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover?max_cook_time=15")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["facets"]["filters_applied"] == 1


@pytest.mark.asyncio
async def test_discover_with_difficulty(client, app):
    """Test discover with difficulty filter."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover?difficulty=easy")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["facets"]["filters_applied"] == 1


@pytest.mark.asyncio
async def test_discover_with_tags(client, app):
    """Test discover with tag filter."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover?tags=keto,high-protein")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["facets"]["filters_applied"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["relevance", "virality", "newest", "calories_asc", "protein_desc", "cook_time_asc"])
async def test_discover_sort_options(sort, app):
    """Test discover with different sort options."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/discover?sort={sort}")
    app.dependency_overrides.clear()
    assert resp.status_code == 200, f"Sort '{sort}' failed"


@pytest.mark.asyncio
async def test_discover_pagination(client, app):
    """Test discover pagination params."""
    mock_session = _mock_session()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    count_result = MagicMock()
    count_result.scalar.return_value = 50
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover?limit=10&offset=20")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["limit"] == 10
    assert data["pagination"]["offset"] == 20
    assert data["pagination"]["has_more"] is True


@pytest.mark.asyncio
async def test_quick_filters(client, app):
    """Test quick filters endpoint returns filter presets with counts."""
    mock_session = _mock_session()

    # Each filter needs a count query
    count_result = MagicMock()
    count_result.scalar.return_value = 42
    mock_session.execute = AsyncMock(return_value=count_result)

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get("/api/v1/discover/quick-filters")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "filters" in data
    assert len(data["filters"]) == 8
    for f in data["filters"]:
        assert "label" in f
        assert "icon" in f
        assert "params" in f
        assert "count" in f


@pytest.mark.asyncio
async def test_discover_combined_filters(client, app):
    """Test discover with multiple filters combined."""
    mock_session = _mock_session()
    recipe = _mock_recipe_row(calories=280, protein=35, cook_time=10, difficulty="easy")

    result = MagicMock()
    result.scalars.return_value.all.return_value = [recipe]
    count_result = MagicMock()
    count_result.scalar.return_value = 1
    mock_session.execute = AsyncMock(side_effect=[result, count_result])

    from src.db.engine import get_session
    app.dependency_overrides[get_session] = lambda: mock_session

    resp = await client.get(
        "/api/v1/discover?q=chicken&max_calories=400&min_protein=25&max_cook_time=15&difficulty=easy&tags=high-protein&sort=protein_desc"
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    # q + calories + protein + cook_time + difficulty + tags = 6
    assert data["facets"]["filters_applied"] == 6
