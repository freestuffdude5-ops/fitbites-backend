"""Social API: follows, activity feed, profile, shares."""
from __future__ import annotations

import secrets
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.social_tables import FollowRow, ActivityRow, RecipeShareRow
from src.db.user_tables import UserRow, SavedRecipeRow
from src.db.tables import RecipeRow
from src.auth import require_user, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["social"])


# ── Models ────────────────────────────────────────────────────────────────────


class FollowRequest(BaseModel):
    user_id: str  # who to follow


class ShareRequest(BaseModel):
    platform: str | None = None  # optional: where they're sharing


class UserProfileResponse(BaseModel):
    id: str
    display_name: str | None
    avatar_url: str | None
    recipe_count: int
    follower_count: int
    following_count: int
    is_following: bool  # whether current user follows this profile


# ── Follow / Unfollow ────────────────────────────────────────────────────────


@router.post("/users/follow")
async def follow_user(
    req: FollowRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Follow another user. Idempotent — re-following returns success."""
    if req.user_id == user.id:
        raise HTTPException(400, "Cannot follow yourself")

    # Verify target exists
    target = await session.execute(select(UserRow).where(UserRow.id == req.user_id))
    if not target.scalar_one_or_none():
        raise HTTPException(404, "User not found")

    # Check if already following
    existing = await session.execute(
        select(FollowRow).where(
            FollowRow.follower_id == user.id,
            FollowRow.following_id == req.user_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_following"}

    follow = FollowRow(follower_id=user.id, following_id=req.user_id)
    session.add(follow)

    # Create activity event
    activity = ActivityRow(
        user_id=user.id,
        action="followed",
        target_user_id=req.user_id,
    )
    session.add(activity)
    await session.commit()
    return {"status": "following"}


@router.delete("/users/follow")
async def unfollow_user(
    req: FollowRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Unfollow a user."""
    result = await session.execute(
        delete(FollowRow).where(
            FollowRow.follower_id == user.id,
            FollowRow.following_id == req.user_id,
        )
    )
    await session.commit()
    return {"status": "unfollowed" if result.rowcount > 0 else "not_following"}


@router.get("/users/{user_id}/followers")
async def get_followers(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List a user's followers with pagination."""
    stmt = (
        select(UserRow)
        .join(FollowRow, FollowRow.follower_id == UserRow.id)
        .where(FollowRow.following_id == user_id)
        .order_by(FollowRow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    users = result.scalars().all()

    count_stmt = select(func.count()).select_from(FollowRow).where(
        FollowRow.following_id == user_id
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "data": [
            {"id": u.id, "display_name": u.display_name, "avatar_url": u.avatar_url}
            for u in users
        ],
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/users/{user_id}/following")
async def get_following(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List who a user follows."""
    stmt = (
        select(UserRow)
        .join(FollowRow, FollowRow.following_id == UserRow.id)
        .where(FollowRow.follower_id == user_id)
        .order_by(FollowRow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    users = result.scalars().all()

    count_stmt = select(func.count()).select_from(FollowRow).where(
        FollowRow.follower_id == user_id
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "data": [
            {"id": u.id, "display_name": u.display_name, "avatar_url": u.avatar_url}
            for u in users
        ],
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


# ── User Profile ──────────────────────────────────────────────────────────────


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    user: UserRow | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a user's public profile with social stats."""
    result = await session.execute(select(UserRow).where(UserRow.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    # Counts
    follower_count = (await session.execute(
        select(func.count()).select_from(FollowRow).where(FollowRow.following_id == user_id)
    )).scalar() or 0

    following_count = (await session.execute(
        select(func.count()).select_from(FollowRow).where(FollowRow.follower_id == user_id)
    )).scalar() or 0

    saved_count = (await session.execute(
        select(func.count()).select_from(SavedRecipeRow).where(SavedRecipeRow.user_id == user_id)
    )).scalar() or 0

    # Check if current user follows this profile
    is_following = False
    if user and user.id != user_id:
        check = await session.execute(
            select(FollowRow).where(
                FollowRow.follower_id == user.id,
                FollowRow.following_id == user_id,
            )
        )
        is_following = check.scalar_one_or_none() is not None

    return {
        "id": target.id,
        "display_name": target.display_name,
        "avatar_url": target.avatar_url,
        "recipe_count": saved_count,
        "follower_count": follower_count,
        "following_count": following_count,
        "is_following": is_following,
        "member_since": target.created_at.isoformat() if target.created_at else None,
    }


# ── Activity Feed ─────────────────────────────────────────────────────────────


@router.get("/feed/activity")
async def activity_feed(
    limit: int = Query(30, ge=1, le=100),
    before: str | None = Query(None, description="ISO timestamp cursor for pagination"),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get activity feed from people the current user follows.

    Returns recent actions (cooked, saved, reviewed, shared) from followed users.
    Cursor-based pagination via `before` timestamp.
    """
    # Get followed user IDs
    following_stmt = select(FollowRow.following_id).where(
        FollowRow.follower_id == user.id
    )
    following_result = await session.execute(following_stmt)
    following_ids = [row[0] for row in following_result.fetchall()]

    if not following_ids:
        return {"data": [], "has_more": False}

    # Build activity query
    stmt = (
        select(ActivityRow, UserRow.display_name, UserRow.avatar_url)
        .join(UserRow, UserRow.id == ActivityRow.user_id)
        .where(ActivityRow.user_id.in_(following_ids))
    )

    if before:
        try:
            cursor_time = datetime.fromisoformat(before)
            stmt = stmt.where(ActivityRow.created_at < cursor_time)
        except ValueError:
            pass

    stmt = stmt.order_by(ActivityRow.created_at.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    rows = result.fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    # Enrich with recipe data where applicable
    recipe_ids = [r[0].recipe_id for r in rows if r[0].recipe_id]
    recipes_map = {}
    if recipe_ids:
        recipe_result = await session.execute(
            select(RecipeRow).where(RecipeRow.id.in_(recipe_ids))
        )
        for recipe in recipe_result.scalars().all():
            recipes_map[recipe.id] = {
                "id": recipe.id,
                "title": recipe.title,
                "thumbnail_url": recipe.thumbnail_url,
                "calories": recipe.calories,
                "protein_g": recipe.protein_g,
            }

    feed = []
    for activity, display_name, avatar_url in rows:
        item = {
            "id": activity.id,
            "user": {
                "id": activity.user_id,
                "display_name": display_name,
                "avatar_url": avatar_url,
            },
            "action": activity.action,
            "created_at": activity.created_at.isoformat() if activity.created_at else None,
            "metadata": activity.extra or {},
        }
        if activity.recipe_id and activity.recipe_id in recipes_map:
            item["recipe"] = recipes_map[activity.recipe_id]
        if activity.target_user_id:
            item["target_user_id"] = activity.target_user_id
        feed.append(item)

    return {
        "data": feed,
        "has_more": has_more,
        "cursor": rows[-1][0].created_at.isoformat() if rows else None,
    }


# ── Recipe Sharing ────────────────────────────────────────────────────────────


@router.post("/recipes/{recipe_id}/share")
async def share_recipe(
    recipe_id: str,
    req: ShareRequest = ShareRequest(),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a trackable share link for a recipe.

    Returns a short share_code that resolves to the recipe.
    Tracks which platform users share to for viral attribution.
    """
    # Verify recipe exists
    recipe = await session.execute(select(RecipeRow).where(RecipeRow.id == recipe_id))
    if not recipe.scalar_one_or_none():
        raise HTTPException(404, "Recipe not found")

    share_code = secrets.token_urlsafe(8)
    share = RecipeShareRow(
        user_id=user.id,
        recipe_id=recipe_id,
        share_code=share_code,
        platform=req.platform,
    )
    session.add(share)

    # Activity event
    activity = ActivityRow(
        user_id=user.id,
        action="shared",
        recipe_id=recipe_id,
        extra={"platform": req.platform} if req.platform else {},
    )
    session.add(activity)
    await session.commit()

    return {
        "share_code": share_code,
        "share_url": f"/s/{share_code}",
        "recipe_id": recipe_id,
    }


@router.get("/s/{share_code}")
async def resolve_share(
    share_code: str,
    session: AsyncSession = Depends(get_session),
):
    """Resolve a share code to the recipe. Increments click counter."""
    result = await session.execute(
        select(RecipeShareRow).where(RecipeShareRow.share_code == share_code)
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Share link not found")

    # Increment clicks
    share.clicks = str(int(share.clicks or "0") + 1)
    await session.commit()

    return {
        "recipe_id": share.recipe_id,
        "shared_by": share.user_id,
        "clicks": int(share.clicks),
    }


# ── Utility: Record Activity (for other modules) ─────────────────────────────


async def record_activity(
    session: AsyncSession,
    user_id: str,
    action: str,
    recipe_id: str | None = None,
    target_user_id: str | None = None,
    metadata: dict | None = None,
):
    """Helper for other modules to record activity events."""
    activity = ActivityRow(
        user_id=user_id,
        action=action,
        recipe_id=recipe_id,
        target_user_id=target_user_id,
        extra=metadata or {},
    )
    session.add(activity)
