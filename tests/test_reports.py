"""Tests for content reporting API."""
import pytest


@pytest.fixture
async def auth(client):
    resp = await client.post("/api/v1/auth/signup", json={
        "email": "reporter@test.com", "password": "pass1234", "display_name": "Reporter"
    })
    data = resp.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


async def test_submit_report(client, auth):
    resp = await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "recipe", "content_id": "test-recipe-1",
        "reason": "misleading", "details": "Nutrition info seems wrong"
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


async def test_duplicate_report_rejected(client, auth):
    await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "recipe", "content_id": "test-recipe-1", "reason": "spam"
    })
    resp = await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "recipe", "content_id": "test-recipe-1", "reason": "misleading"
    })
    assert resp.status_code == 409


async def test_invalid_content_type(client, auth):
    resp = await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "invalid", "content_id": "123", "reason": "spam"
    })
    assert resp.status_code == 400


async def test_invalid_reason(client, auth):
    resp = await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "recipe", "content_id": "123", "reason": "invalid_reason"
    })
    assert resp.status_code == 400


async def test_my_reports(client, auth):
    await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "comment", "content_id": "c1", "reason": "harassment"
    })
    resp = await client.get("/api/v1/reports/my", headers=auth)
    assert resp.status_code == 200
    assert len(resp.json()["reports"]) >= 1


async def test_admin_list_reports(client, auth):
    await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "review", "content_id": "r1", "reason": "spam"
    })
    resp = await client.get("/api/v1/admin/reports?status=pending", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_admin_update_report(client, auth):
    r = await client.post("/api/v1/reports", headers=auth, json={
        "content_type": "user", "content_id": "u1", "reason": "spam"
    })
    report_id = r.json()["id"]
    resp = await client.patch(f"/api/v1/admin/reports/{report_id}", headers=auth, json={
        "status": "resolved", "admin_notes": "Action taken"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


async def test_requires_auth(client):
    resp = await client.post("/api/v1/reports", json={
        "content_type": "recipe", "content_id": "123", "reason": "spam"
    })
    assert resp.status_code == 401
