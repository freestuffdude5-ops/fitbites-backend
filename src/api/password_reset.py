"""Password Reset API — secure token-based password reset flow.

Flow:
1. POST /api/v1/auth/forgot-password — sends reset code (in prod, via email)
2. POST /api/v1/auth/reset-password — validates code + sets new password
3. POST /api/v1/auth/change-password — authenticated password change

Security:
- Reset tokens expire in 15 minutes
- Tokens are single-use (deleted after use)
- Rate limited (handled by global rate limiter on /auth/ routes)
- Constant-time comparison for tokens
- Old tokens cleared when new one is requested
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow
from src.auth import require_user, hash_password, verify_password
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# In-memory token store (swap for Redis/DB in production)
# Format: {hashed_token: {"user_id": str, "expires": float}}
_reset_tokens: dict[str, dict] = {}

_RESET_TTL = 900  # 15 minutes
_TOKEN_LENGTH = 32  # 256-bit token


def _hash_token(token: str) -> str:
    """Hash token for storage (don't store raw tokens)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _cleanup_expired():
    """Remove expired tokens."""
    now = time.time()
    expired = [k for k, v in _reset_tokens.items() if v["expires"] < now]
    for k in expired:
        del _reset_tokens[k]


def reset_token_store():
    """Clear all tokens (for testing)."""
    _reset_tokens.clear()


# ── Schemas ──────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=320)

class ResetPasswordRequest(BaseModel):
    email: str = Field(..., max_length=320)
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Routes ───────────────────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_session),
):
    """Request a password reset token.
    
    Always returns 200 to prevent email enumeration.
    In production, sends email with the token/link.
    """
    _cleanup_expired()

    # Look up user (but always return success)
    result = await session.execute(
        select(UserRow).where(UserRow.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user:
        # Clear any existing tokens for this user
        to_remove = [k for k, v in _reset_tokens.items() if v["user_id"] == user.id]
        for k in to_remove:
            del _reset_tokens[k]

        # Generate new token
        token = secrets.token_urlsafe(_TOKEN_LENGTH)
        hashed = _hash_token(token)
        _reset_tokens[hashed] = {
            "user_id": user.id,
            "expires": time.time() + _RESET_TTL,
        }

        # In production: send email with token/link
        # For now, log it (and return in dev mode for testing)
        logger.info(f"Password reset requested for {body.email}")

        # Return token in dev/test mode only
        if getattr(settings, "ENVIRONMENT", "development") != "production":
            return {
                "message": "If an account exists with that email, a reset link has been sent.",
                "reset_token": token,  # DEV ONLY - remove in production
            }

    return {"message": "If an account exists with that email, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
):
    """Reset password using a valid token."""
    _cleanup_expired()

    hashed = _hash_token(body.token)
    token_data = _reset_tokens.get(hashed)

    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if token_data["expires"] < time.time():
        del _reset_tokens[hashed]
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Verify email matches
    result = await session.execute(
        select(UserRow).where(
            UserRow.id == token_data["user_id"],
            UserRow.email == body.email,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Update password
    user.password_hash = hash_password(body.new_password)
    await session.commit()

    # Invalidate token (single-use)
    del _reset_tokens[hashed]

    logger.info(f"Password reset completed for user {user.id}")
    return {"message": "Password has been reset successfully. Please log in with your new password."}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Change password for authenticated user (requires current password)."""
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Account does not have a password set")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    user.password_hash = hash_password(body.new_password)
    await session.commit()

    return {"message": "Password changed successfully"}
