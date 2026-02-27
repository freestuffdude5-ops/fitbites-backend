"""Test calorie tracking endpoints using httpx TestClient."""
import asyncio
import sys
sys.path.insert(0, ".")

from httpx import AsyncClient, ASGITransport
from src.api.main import app
from src.auth import create_tokens

async def main():
    # Create a token for user cd9a4445-504b-41fe-9244-2f1f364f8c57
    tokens = create_tokens("cd9a4445-504b-41fe-9244-2f1f364f8c57")
    token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        print("=== 1. POST /tracking/log-meal (Chicken) ===")
        r = await client.post("/api/v1/tracking/log-meal", json={
            "name": "Chicken Breast", "calories": 350, "protein": 45, "carbs": 5, "fat": 12
        }, headers=headers)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.json()}")
        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"

        print("\n=== 2. POST /tracking/log-meal (Rice) ===")
        r = await client.post("/api/v1/tracking/log-meal", json={
            "name": "Brown Rice Bowl", "calories": 420, "protein": 12, "carbs": 80, "fat": 8
        }, headers=headers)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.json()}")
        assert r.status_code == 201

        print("\n=== 3. PUT /tracking/daily-goal ===")
        r = await client.put("/api/v1/tracking/daily-goal", json={
            "daily_calories": 2200, "daily_protein": 180, "daily_carbs": 220, "daily_fat": 70
        }, headers=headers)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.json()}")
        assert r.status_code == 200

        print("\n=== 4. GET /tracking/daily-summary ===")
        r = await client.get("/api/v1/tracking/daily-summary", headers=headers)
        print(f"  Status: {r.status_code}")
        data = r.json()
        print(f"  Body: {data}")
        assert r.status_code == 200
        assert data["eaten"]["calories"] >= 770  # at least 350 + 420
        assert data["goal"]["calories"] == 2200
        assert data["meal_count"] >= 2

        print("\n=== 5. GET /tracking/history ===")
        r = await client.get("/api/v1/tracking/history", headers=headers)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {r.json()}")
        assert r.status_code == 200
        assert len(r.json()) >= 2

        print("\n✅ ALL TESTS PASSED!")

asyncio.run(main())
