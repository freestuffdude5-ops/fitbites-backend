"""Tests for meal planning API."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow
from src.models import Platform

from tests.conftest import get_test_session


async def _seed(session):
    user = UserRow(id="mp-user-1", device_id="mp-dev-1", preferences={})
    session.add(user)
    for i in range(5):
        session.add(RecipeRow(
            id=f"mp-recipe-{i}",
            title=f"Recipe {i}",
            description=f"Desc {i}",
            creator_username="chef",
            creator_platform=Platform.YOUTUBE,
            creator_profile_url="https://youtube.com/@chef",
            platform=Platform.YOUTUBE,
            source_url=f"https://youtube.com/watch?v=mp{i}",
            ingredients=[{"name": "chicken", "quantity": "200g"}],
            steps=["Cook"],
            tags=["high-protein"],
            calories=400 + i * 50,
            protein_g=30 + i * 5,
            carbs_g=30,
            fat_g=15,
            virality_score=80 + i,
        ))
    await session.commit()


@pytest.mark.asyncio
async def test_create_meal_plan():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "name": "Week 1",
            "start_date": "2026-03-02",
            "days": 7,
            "daily_calories": 2000,
            "daily_protein_g": 150,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Week 1"
        assert data["days"] == 7
        assert data["daily_targets"]["calories"] == 2000
        return data["id"]


@pytest.mark.asyncio
async def test_add_and_get_meal_entry():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create plan
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7, "daily_calories": 2000,
        })
        plan_id = resp.json()["id"]

        # Add entry
        resp = await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-0",
            "day_index": 0,
            "meal_type": "breakfast",
            "servings": 1.5,
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "added"

        # Get plan with entries
        resp = await client.get(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        assert resp.status_code == 200
        plan = resp.json()
        assert len(plan["days"]) == 7
        day0 = plan["days"][0]
        assert len(day0["entries"]) == 1
        assert day0["entries"][0]["meal_type"] == "breakfast"
        assert day0["totals"]["calories"] == 600  # 400 * 1.5


@pytest.mark.asyncio
async def test_meal_plan_daily_totals():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7,
            "daily_calories": 2000, "daily_protein_g": 100,
        })
        plan_id = resp.json()["id"]

        # Add breakfast + lunch
        await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-0", "day_index": 0, "meal_type": "breakfast",
        })
        await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-1", "day_index": 0, "meal_type": "lunch",
        })

        resp = await client.get(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        day0 = resp.json()["days"][0]
        assert day0["totals"]["calories"] == 850  # 400 + 450
        assert day0["totals"]["protein_g"] == 65.0  # 30 + 35
        assert day0["targets_met"]["calories"] is True
        assert day0["targets_met"]["protein"] is False  # 65 < 100


@pytest.mark.asyncio
async def test_delete_meal_entry():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7,
        })
        plan_id = resp.json()["id"]

        resp = await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-0", "day_index": 0, "meal_type": "breakfast",
        })
        entry_id = resp.json()["entry_id"]

        resp = await client.delete(
            f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries/{entry_id}"
        )
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_meal_plan():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7,
        })
        plan_id = resp.json()["id"]

        resp = await client.delete(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_meal_plans():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "name": "Plan A", "start_date": "2026-03-02", "days": 7,
        })
        await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "name": "Plan B", "start_date": "2026-03-09", "days": 7,
        })

        resp = await client.get("/api/v1/users/mp-user-1/meal-plans")
        assert resp.status_code == 200
        plans = resp.json()["data"]
        assert len(plans) == 2
        assert plans[0]["name"] == "Plan B"  # Most recent first


@pytest.mark.asyncio
async def test_auto_fill_meal_plan():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 3,
            "daily_calories": 2000, "daily_protein_g": 100,
        })
        plan_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/auto-fill",
            json={"meal_types": ["breakfast", "lunch", "dinner"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filled"] == 9  # 3 days * 3 meals
        assert data["total_slots"] == 9

        # Verify entries were actually created
        resp = await client.get(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        plan = resp.json()
        total_entries = sum(len(d["entries"]) for d in plan["days"])
        assert total_entries == 9


@pytest.mark.asyncio
async def test_meal_plan_404_wrong_user():
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7,
        })
        plan_id = resp.json()["id"]

        # Try to access with wrong user
        resp = await client.get(f"/api/v1/users/wrong-user/meal-plans/{plan_id}")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_idempotent_entry_update():
    """Adding same recipe to same slot should update, not duplicate."""
    async with get_test_session() as session:
        await _seed(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/mp-user-1/meal-plans", json={
            "start_date": "2026-03-02", "days": 7,
        })
        plan_id = resp.json()["id"]

        # Add same recipe twice
        await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-0", "day_index": 0, "meal_type": "breakfast", "servings": 1,
        })
        resp = await client.post(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}/entries", json={
            "recipe_id": "mp-recipe-0", "day_index": 0, "meal_type": "breakfast", "servings": 2,
        })
        assert resp.json()["status"] == "updated"

        # Should only have 1 entry
        resp = await client.get(f"/api/v1/users/mp-user-1/meal-plans/{plan_id}")
        day0 = resp.json()["days"][0]
        assert len(day0["entries"]) == 1
