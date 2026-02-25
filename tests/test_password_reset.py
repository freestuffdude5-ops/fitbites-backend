"""Tests for password reset and change password flows."""
import pytest


@pytest.fixture(autouse=True)
def clear_tokens():
    """Clear reset tokens between tests."""
    from src.api.password_reset import reset_token_store
    reset_token_store()
    yield
    reset_token_store()


@pytest.fixture
async def user_auth(client):
    """Create user and return (headers, email, password)."""
    email, password = "reset@test.com", "oldpass1234"
    resp = await client.post("/api/v1/auth/signup", json={
        "email": email, "password": password, "display_name": "Reset User"
    })
    data = resp.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return headers, email, password


# ── Forgot Password ─────────────────────────────────────────────────────

async def test_forgot_password_returns_token_in_dev(client, user_auth):
    _, email, _ = user_auth
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    data = resp.json()
    assert "reset_token" in data  # Dev mode returns token


async def test_forgot_password_unknown_email_still_200(client):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200
    assert "reset_token" not in resp.json()


# ── Reset Password ───────────────────────────────────────────────────────

async def test_reset_password_success(client, user_auth):
    _, email, _ = user_auth
    # Get token
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = resp.json()["reset_token"]

    # Reset
    resp = await client.post("/api/v1/auth/reset-password", json={
        "email": email, "token": token, "new_password": "newpass5678"
    })
    assert resp.status_code == 200

    # Login with new password
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "newpass5678"
    })
    assert resp.status_code == 200


async def test_reset_password_invalid_token(client, user_auth):
    _, email, _ = user_auth
    resp = await client.post("/api/v1/auth/reset-password", json={
        "email": email, "token": "invalid-token", "new_password": "newpass5678"
    })
    assert resp.status_code == 400


async def test_reset_token_single_use(client, user_auth):
    _, email, _ = user_auth
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = resp.json()["reset_token"]

    # First use — success
    resp = await client.post("/api/v1/auth/reset-password", json={
        "email": email, "token": token, "new_password": "newpass5678"
    })
    assert resp.status_code == 200

    # Second use — fail
    resp = await client.post("/api/v1/auth/reset-password", json={
        "email": email, "token": token, "new_password": "anotherpass"
    })
    assert resp.status_code == 400


async def test_reset_wrong_email(client, user_auth):
    _, email, _ = user_auth
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = resp.json()["reset_token"]

    resp = await client.post("/api/v1/auth/reset-password", json={
        "email": "wrong@test.com", "token": token, "new_password": "newpass5678"
    })
    assert resp.status_code == 400


# ── Change Password ─────────────────────────────────────────────────────

async def test_change_password_success(client, user_auth):
    headers, email, password = user_auth
    resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": password, "new_password": "changed1234"
    })
    assert resp.status_code == 200

    # Login with new password
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "changed1234"
    })
    assert resp.status_code == 200


async def test_change_password_wrong_current(client, user_auth):
    headers, _, _ = user_auth
    resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": "wrongpass", "new_password": "changed1234"
    })
    assert resp.status_code == 401


async def test_change_password_same_password_rejected(client, user_auth):
    headers, _, password = user_auth
    resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": password, "new_password": password
    })
    assert resp.status_code == 400


async def test_change_password_requires_auth(client):
    resp = await client.post("/api/v1/auth/change-password", json={
        "current_password": "old", "new_password": "newpass1234"
    })
    assert resp.status_code == 401


async def test_new_password_min_length(client, user_auth):
    headers, _, password = user_auth
    resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": password, "new_password": "short"
    })
    assert resp.status_code == 422  # Validation error
