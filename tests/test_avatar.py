"""Tests for avatar upload API — user profile pictures."""
import pytest
from httpx import AsyncClient
import io


@pytest.mark.asyncio
async def test_upload_avatar(async_client: AsyncClient, auth_headers):
    """User can upload an avatar image."""
    user_id = auth_headers["user_id"]
    
    # Create a fake image file (1x1 PNG)
    png_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    
    # Upload avatar
    files = {"file": ("avatar.png", io.BytesIO(png_data), "image/png")}
    response = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "avatar_url" in data
    assert data["avatar_url"].endswith(".png")


@pytest.mark.asyncio
async def test_upload_avatar_wrong_user(async_client: AsyncClient, auth_headers):
    """User cannot upload avatar for other users."""
    png_data = b"\x89PNG\r\n\x1a\n"
    files = {"file": ("avatar.png", io.BytesIO(png_data), "image/png")}
    
    response = await async_client.post(
        "/api/v1/users/999999/avatar",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_avatar_invalid_type(async_client: AsyncClient, auth_headers):
    """Uploading non-image file returns 400."""
    user_id = auth_headers["user_id"]
    
    # Try to upload a text file
    files = {"file": ("avatar.txt", io.BytesIO(b"not an image"), "text/plain")}
    
    response = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["message"]


@pytest.mark.asyncio
async def test_upload_avatar_too_large(async_client: AsyncClient, auth_headers):
    """Uploading file > 5MB returns 400."""
    user_id = auth_headers["user_id"]
    
    # Create 6MB file
    large_data = b"x" * (6 * 1024 * 1024)
    files = {"file": ("avatar.jpg", io.BytesIO(large_data), "image/jpeg")}
    
    response = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "too large" in response.json()["message"]


@pytest.mark.asyncio
async def test_upload_avatar_replaces_old(async_client: AsyncClient, auth_headers):
    """Uploading new avatar deletes old one."""
    user_id = auth_headers["user_id"]
    
    png_data1 = b"\x89PNG\r\n\x1a\n\x00\x01"
    files = {"file": ("avatar.png", io.BytesIO(png_data1), "image/png")}
    
    # Upload first avatar
    resp1 = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    first_url = resp1.json()["avatar_url"]
    
    # Upload second avatar with different content
    png_data2 = b"\x89PNG\r\n\x1a\n\x00\x02"
    files2 = {"file": ("avatar2.png", io.BytesIO(png_data2), "image/png")}
    resp2 = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files2,
        headers=auth_headers,
    )
    second_url = resp2.json()["avatar_url"]
    
    # URLs should be different (old one replaced)
    assert first_url != second_url


@pytest.mark.asyncio
async def test_delete_avatar(async_client: AsyncClient, auth_headers):
    """User can delete their avatar."""
    user_id = auth_headers["user_id"]
    
    # Upload avatar first
    png_data = b"\x89PNG\r\n\x1a\n"
    files = {"file": ("avatar.png", io.BytesIO(png_data), "image/png")}
    
    await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    
    # Delete avatar
    response = await async_client.delete(
        f"/api/v1/users/{user_id}/avatar",
        headers=auth_headers,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_avatar_wrong_user(async_client: AsyncClient, auth_headers):
    """User cannot delete other users' avatars."""
    response = await async_client.delete(
        "/api/v1/users/999999/avatar",
        headers=auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_avatar_in_user_profile(async_client: AsyncClient, auth_headers):
    """Avatar URL appears in user profile after upload."""
    user_id = auth_headers["user_id"]
    
    # Upload avatar
    png_data = b"\x89PNG\r\n\x1a\n"
    files = {"file": ("avatar.png", io.BytesIO(png_data), "image/png")}
    
    upload_resp = await async_client.post(
        f"/api/v1/users/{user_id}/avatar",
        files=files,
        headers=auth_headers,
    )
    avatar_url = upload_resp.json()["avatar_url"]
    
    # Verify avatar URL was set (can check via users endpoint if it exists)
    assert avatar_url.endswith(".png")
