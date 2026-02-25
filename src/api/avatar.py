"""Avatar upload API — User profile pictures with storage."""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_user
from src.db.engine import get_session
from src.db.user_tables import UserRow
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Avatar storage config
AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class AvatarUploadResponse(BaseModel):
    """Avatar upload result."""
    avatar_url: str


@router.post("/api/v1/users/{user_id}/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(
    user_id: str,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
):
    """Upload user avatar image."""
    if user.id != user_id:
        raise HTTPException(403, "Cannot upload avatar for other users")
    
    # Validate file type
    if not file.filename:
        raise HTTPException(400, "No filename provided")
    
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    
    # Read file content
    content = await file.read()
    
    # Validate size
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(400, f"File too large. Max size: {MAX_AVATAR_SIZE / 1024 / 1024:.1f}MB")
    
    # Generate unique filename (hash content for deduplication)
    content_hash = hashlib.sha256(content).hexdigest()[:16]
    filename = f"{user_id}_{content_hash}{ext}"
    filepath = AVATAR_DIR / filename
    
    # Delete old avatar if exists
    if user.avatar_url:
        old_filename = user.avatar_url.split("/")[-1]
        old_path = AVATAR_DIR / old_filename
        if old_path.exists():
            old_path.unlink()
            logger.info(f"Deleted old avatar: {old_filename}")
    
    # Save new avatar
    with open(filepath, "wb") as f:
        f.write(content)
    
    # Update user record
    avatar_url = f"{settings.API_BASE_URL}/static/avatars/{filename}"
    user.avatar_url = avatar_url
    await session.commit()
    
    logger.info(f"User {user_id} uploaded avatar: {filename}")
    
    return AvatarUploadResponse(avatar_url=avatar_url)


@router.delete("/api/v1/users/{user_id}/avatar", status_code=204)
async def delete_avatar(
    user_id: str,
    user: Annotated[UserRow, Depends(require_user)],
    session: AsyncSession = Depends(get_session),
):
    """Delete user avatar."""
    if user.id != user_id:
        raise HTTPException(403, "Cannot delete avatar for other users")
    
    # Delete file
    if user.avatar_url:
        filename = user.avatar_url.split("/")[-1]
        filepath = AVATAR_DIR / filename
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted avatar file: {filename}")
    
    # Update user record
    user.avatar_url = None
    await session.commit()
    
    logger.info(f"User {user_id} deleted avatar")
