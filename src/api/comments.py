"""Comments API — Casual social conversation on recipes (distinct from reviews)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_user
from src.db.engine import get_session
from src.db.comment_tables import CommentRow, CommentLikeRow
from src.db.user_tables import UserRow

logger = logging.getLogger(__name__)
router = APIRouter()


class CommentCreate(BaseModel):
    """Request to post a comment."""
    text: str = Field(..., min_length=1, max_length=2000, description="Comment text")
    parent_id: int | None = Field(None, description="Parent comment ID for replies")


class CommentUpdate(BaseModel):
    """Request to edit a comment."""
    text: str = Field(..., min_length=1, max_length=2000)


class CommentAuthor(BaseModel):
    """Comment author info."""
    id: int
    display_name: str
    avatar_url: str | None = None


class CommentResponse(BaseModel):
    """Comment with metadata."""
    id: int
    recipe_id: str
    author: CommentAuthor
    text: str
    parent_id: int | None
    reply_count: int
    like_count: int
    is_liked: bool
    is_author: bool
    created_at: datetime
    updated_at: datetime | None


class CommentsListResponse(BaseModel):
    """Paginated comments list."""
    comments: list[CommentResponse]
    total: int
    has_more: bool


@router.post("/api/v1/recipes/{recipe_id}/comments", response_model=CommentResponse)
async def post_comment(
    recipe_id: str,
    req: CommentCreate,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Post a comment on a recipe (or reply to another comment)."""
    # Verify parent comment exists if replying
    if req.parent_id:
        parent = await session.get(CommentRow, req.parent_id)
        if not parent or parent.recipe_id != recipe_id:
            raise HTTPException(404, "Parent comment not found")
    
    comment = CommentRow(
        recipe_id=recipe_id,
        user_id=user.id,
        text=req.text,
        parent_id=req.parent_id,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    
    logger.info(f"User {user.id} posted comment {comment.id} on recipe {recipe_id}")
    
    return CommentResponse(
        id=comment.id,
        recipe_id=comment.recipe_id,
        author=CommentAuthor(
            id=user.id,
            display_name=user.display_name or user.email.split("@")[0],
            avatar_url=user.avatar_url,
        ),
        text=comment.text,
        parent_id=comment.parent_id,
        reply_count=0,
        like_count=0,
        is_liked=False,
        is_author=True,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.get("/api/v1/recipes/{recipe_id}/comments", response_model=CommentsListResponse)
async def get_comments(
    recipe_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("newest", pattern="^(newest|oldest|top)$"),
    user: UserRow | None = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List comments on a recipe with nested replies."""
    # Get top-level comments (parent_id is null)
    query = (
        select(CommentRow, UserRow)
        .join(UserRow, CommentRow.user_id == UserRow.id)
        .where(CommentRow.recipe_id == recipe_id, CommentRow.parent_id.is_(None))
    )
    
    # Sort
    if sort == "newest":
        query = query.order_by(CommentRow.created_at.desc())
    elif sort == "oldest":
        query = query.order_by(CommentRow.created_at.asc())
    elif sort == "top":
        query = query.order_by(CommentRow.like_count.desc(), CommentRow.created_at.desc())
    
    # Paginate
    total_result = await session.execute(
        select(func.count()).select_from(CommentRow).where(
            CommentRow.recipe_id == recipe_id,
            CommentRow.parent_id.is_(None),
        )
    )
    total = total_result.scalar() or 0
    
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    rows = result.all()
    
    # Get user's likes if authenticated
    liked_comment_ids = set()
    if user:
        likes_result = await session.execute(
            select(CommentLikeRow.comment_id).where(CommentLikeRow.user_id == user.id)
        )
        liked_comment_ids = {row[0] for row in likes_result.all()}
    
    # Build response
    comments = []
    for comment, author in rows:
        # Count replies
        reply_count_result = await session.execute(
            select(func.count()).select_from(CommentRow).where(CommentRow.parent_id == comment.id)
        )
        reply_count = reply_count_result.scalar() or 0
        
        comments.append(CommentResponse(
            id=comment.id,
            recipe_id=comment.recipe_id,
            author=CommentAuthor(
                id=author.id,
                display_name=author.display_name or author.email.split("@")[0],
                avatar_url=author.avatar_url,
            ),
            text=comment.text,
            parent_id=comment.parent_id,
            reply_count=reply_count,
            like_count=comment.like_count,
            is_liked=comment.id in liked_comment_ids,
            is_author=user.id == comment.user_id if user else False,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        ))
    
    return CommentsListResponse(
        comments=comments,
        total=total,
        has_more=(offset + limit < total),
    )


@router.get("/api/v1/comments/{comment_id}/replies", response_model=CommentsListResponse)
async def get_replies(
    comment_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: UserRow | None = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Get replies to a specific comment."""
    # Verify parent comment exists
    parent = await session.get(CommentRow, comment_id)
    if not parent:
        raise HTTPException(404, "Comment not found")
    
    # Get replies
    query = (
        select(CommentRow, UserRow)
        .join(UserRow, CommentRow.user_id == UserRow.id)
        .where(CommentRow.parent_id == comment_id)
        .order_by(CommentRow.created_at.asc())
    )
    
    total_result = await session.execute(
        select(func.count()).select_from(CommentRow).where(CommentRow.parent_id == comment_id)
    )
    total = total_result.scalar() or 0
    
    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    rows = result.all()
    
    # Get user's likes if authenticated
    liked_comment_ids = set()
    if user:
        likes_result = await session.execute(
            select(CommentLikeRow.comment_id).where(CommentLikeRow.user_id == user.id)
        )
        liked_comment_ids = {row[0] for row in likes_result.all()}
    
    comments = []
    for comment, author in rows:
        comments.append(CommentResponse(
            id=comment.id,
            recipe_id=comment.recipe_id,
            author=CommentAuthor(
                id=author.id,
                display_name=author.display_name or author.email.split("@")[0],
                avatar_url=author.avatar_url,
            ),
            text=comment.text,
            parent_id=comment.parent_id,
            reply_count=0,  # No nested replies for now
            like_count=comment.like_count,
            is_liked=comment.id in liked_comment_ids,
            is_author=user.id == comment.user_id if user else False,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        ))
    
    return CommentsListResponse(
        comments=comments,
        total=total,
        has_more=(offset + limit < total),
    )


@router.patch("/api/v1/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: int,
    req: CommentUpdate,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Edit your own comment."""
    comment = await session.get(CommentRow, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.user_id != user.id:
        raise HTTPException(403, "Not your comment")
    
    comment.text = req.text
    comment.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(comment)
    
    # Get reply count
    reply_count_result = await session.execute(
        select(func.count()).select_from(CommentRow).where(CommentRow.parent_id == comment.id)
    )
    reply_count = reply_count_result.scalar() or 0
    
    # Check if liked
    like_result = await session.execute(
        select(CommentLikeRow).where(
            CommentLikeRow.comment_id == comment_id,
            CommentLikeRow.user_id == user.id,
        )
    )
    is_liked = like_result.scalar_one_or_none() is not None
    
    return CommentResponse(
        id=comment.id,
        recipe_id=comment.recipe_id,
        author=CommentAuthor(
            id=user.id,
            display_name=user.display_name or user.email.split("@")[0],
            avatar_url=user.avatar_url,
        ),
        text=comment.text,
        parent_id=comment.parent_id,
        reply_count=reply_count,
        like_count=comment.like_count,
        is_liked=is_liked,
        is_author=True,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.delete("/api/v1/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: int,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Delete your own comment."""
    comment = await session.get(CommentRow, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.user_id != user.id:
        raise HTTPException(403, "Not your comment")
    
    # Delete associated likes
    await session.execute(
        delete(CommentLikeRow).where(CommentLikeRow.comment_id == comment_id)
    )
    
    # Delete comment
    await session.delete(comment)
    await session.commit()
    
    logger.info(f"User {user.id} deleted comment {comment_id}")


@router.post("/api/v1/comments/{comment_id}/like", status_code=204)
async def toggle_comment_like(
    comment_id: int,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Toggle like on a comment."""
    comment = await session.get(CommentRow, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    
    # Check if already liked
    like_result = await session.execute(
        select(CommentLikeRow).where(
            CommentLikeRow.comment_id == comment_id,
            CommentLikeRow.user_id == user.id,
        )
    )
    existing_like = like_result.scalar_one_or_none()
    
    if existing_like:
        # Unlike
        await session.delete(existing_like)
        await session.execute(
            update(CommentRow)
            .where(CommentRow.id == comment_id)
            .values(like_count=CommentRow.like_count - 1)
        )
        logger.info(f"User {user.id} unliked comment {comment_id}")
    else:
        # Like
        like = CommentLikeRow(comment_id=comment_id, user_id=user.id)
        session.add(like)
        await session.execute(
            update(CommentRow)
            .where(CommentRow.id == comment_id)
            .values(like_count=CommentRow.like_count + 1)
        )
        logger.info(f"User {user.id} liked comment {comment_id}")
    
    await session.commit()
