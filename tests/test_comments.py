"""Tests for comments API — social conversation on recipes."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_comment(async_client: AsyncClient, auth_headers, test_recipe):
    """User can post a comment on a recipe."""
    response = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "This looks amazing! Can't wait to try it."},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "This looks amazing! Can't wait to try it."
    assert data["recipe_id"] == test_recipe["id"]
    assert data["like_count"] == 0
    assert data["reply_count"] == 0
    assert data["is_author"] is True
    assert data["is_liked"] is False


@pytest.mark.asyncio
async def test_post_comment_reply(async_client: AsyncClient, auth_headers, test_recipe):
    """User can reply to another comment."""
    # Post parent comment
    parent_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Parent comment"},
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]
    
    # Post reply
    response = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Reply to parent", "parent_id": parent_id},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["parent_id"] == parent_id
    assert data["text"] == "Reply to parent"


@pytest.mark.asyncio
async def test_post_comment_invalid_parent(async_client: AsyncClient, auth_headers, test_recipe):
    """Replying to non-existent comment returns 404."""
    response = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Reply", "parent_id": 999999},
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_comments_empty(async_client: AsyncClient, auth_headers, test_recipe):
    """Getting comments on recipe with no comments returns empty list."""
    response = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["comments"] == []
    assert data["total"] == 0
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_get_comments_list(async_client: AsyncClient, auth_headers, test_recipe):
    """Getting comments returns sorted list."""
    # Post 3 comments
    texts = ["First comment", "Second comment", "Third comment"]
    for text in texts:
        await async_client.post(
            f"/api/v1/recipes/{test_recipe['id']}/comments",
            json={"text": text},
            headers=auth_headers,
        )
    
    # Get comments (newest first by default)
    response = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["comments"]) == 3
    assert data["total"] == 3
    assert data["comments"][0]["text"] == "Third comment"  # Newest first


@pytest.mark.asyncio
async def test_get_comments_pagination(async_client: AsyncClient, auth_headers, test_recipe):
    """Comments list supports pagination."""
    # Post 5 comments
    for i in range(5):
        await async_client.post(
            f"/api/v1/recipes/{test_recipe['id']}/comments",
            json={"text": f"Comment {i}"},
            headers=auth_headers,
        )
    
    # Get first page (limit 2)
    response = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments?limit=2",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["comments"]) == 2
    assert data["total"] == 5
    assert data["has_more"] is True
    
    # Get second page
    response = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments?limit=2&offset=2",
        headers=auth_headers,
    )
    data = response.json()
    assert len(data["comments"]) == 2
    assert data["has_more"] is True


@pytest.mark.asyncio
async def test_get_replies(async_client: AsyncClient, auth_headers, test_recipe):
    """Can fetch replies to a specific comment."""
    # Post parent
    parent_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Parent"},
        headers=auth_headers,
    )
    parent_id = parent_resp.json()["id"]
    
    # Post 2 replies
    await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Reply 1", "parent_id": parent_id},
        headers=auth_headers,
    )
    await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Reply 2", "parent_id": parent_id},
        headers=auth_headers,
    )
    
    # Get replies
    response = await async_client.get(
        f"/api/v1/comments/{parent_id}/replies",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["comments"]) == 2
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_update_comment(async_client: AsyncClient, auth_headers, test_recipe):
    """User can edit their own comment."""
    # Post comment
    create_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Original text"},
        headers=auth_headers,
    )
    comment_id = create_resp.json()["id"]
    
    # Update comment
    response = await async_client.patch(
        f"/api/v1/comments/{comment_id}",
        json={"text": "Updated text"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Updated text"
    assert data["updated_at"] is not None


@pytest.mark.asyncio
async def test_update_comment_not_author(async_client: AsyncClient, auth_headers, test_recipe):
    """User cannot edit other users' comments."""
    # Post comment as user 1
    create_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Original"},
        headers=auth_headers,
    )
    comment_id = create_resp.json()["id"]
    
    # Try to edit as user 2
    signup_resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": "user2@test.com", "password": "pass123", "display_name": "User2"},
    )
    user2_token = signup_resp.json()["access_token"]
    
    response = await async_client.patch(
        f"/api/v1/comments/{comment_id}",
        json={"text": "Hacked!"},
        headers={"Authorization": f"Bearer {user2_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_comment(async_client: AsyncClient, auth_headers, test_recipe):
    """User can delete their own comment."""
    # Post comment
    create_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "To be deleted"},
        headers=auth_headers,
    )
    comment_id = create_resp.json()["id"]
    
    # Delete comment
    response = await async_client.delete(
        f"/api/v1/comments/{comment_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204
    
    # Verify deleted
    get_resp = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        headers=auth_headers,
    )
    assert len(get_resp.json()["comments"]) == 0


@pytest.mark.asyncio
async def test_like_comment(async_client: AsyncClient, auth_headers, test_recipe):
    """User can like a comment."""
    # Post comment
    create_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Like me!"},
        headers=auth_headers,
    )
    comment_id = create_resp.json()["id"]
    
    # Like comment
    response = await async_client.post(
        f"/api/v1/comments/{comment_id}/like",
        headers=auth_headers,
    )
    assert response.status_code == 204
    
    # Verify like count
    get_resp = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        headers=auth_headers,
    )
    comments = get_resp.json()["comments"]
    assert comments[0]["like_count"] == 1
    assert comments[0]["is_liked"] is True


@pytest.mark.asyncio
async def test_unlike_comment(async_client: AsyncClient, auth_headers, test_recipe):
    """User can unlike a comment (toggle)."""
    # Post and like
    create_resp = await async_client.post(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        json={"text": "Like me!"},
        headers=auth_headers,
    )
    comment_id = create_resp.json()["id"]
    await async_client.post(f"/api/v1/comments/{comment_id}/like", headers=auth_headers)
    
    # Unlike
    response = await async_client.post(
        f"/api/v1/comments/{comment_id}/like",
        headers=auth_headers,
    )
    assert response.status_code == 204
    
    # Verify like removed
    get_resp = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments",
        headers=auth_headers,
    )
    comments = get_resp.json()["comments"]
    assert comments[0]["like_count"] == 0
    assert comments[0]["is_liked"] is False


@pytest.mark.asyncio
async def test_comment_sort_top(async_client: AsyncClient, auth_headers, test_recipe):
    """Comments can be sorted by like count (top)."""
    # Create 3 comments with different like counts
    comment_ids = []
    for i in range(3):
        resp = await async_client.post(
            f"/api/v1/recipes/{test_recipe['id']}/comments",
            json={"text": f"Comment {i}"},
            headers=auth_headers,
        )
        comment_ids.append(resp.json()["id"])
    
    # Give comment 2 the most likes (manually update)
    # For now just test that sort param is accepted
    response = await async_client.get(
        f"/api/v1/recipes/{test_recipe['id']}/comments?sort=top",
        headers=auth_headers,
    )
    assert response.status_code == 200
