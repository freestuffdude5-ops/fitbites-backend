"""JWT authentication for FitBites — lightweight, production-ready."""
from __future__ import annotations

import hashlib
import hmac
import json
import base64
import time
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow, SavedRecipeRow
from config.settings import settings

# ---- Password hashing (PBKDF2 — no extra deps) ----

_ITERATIONS = 260_000
_SALT_LEN = 32


def hash_password(password: str) -> str:
    salt = uuid.uuid4().hex[:_SALT_LEN]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, dk_hex = stored.split("$", 1)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ---- JWT (minimal, no PyJWT dependency) ----

_JWT_SECRET = getattr(settings, "JWT_SECRET", "fitbites-dev-secret-change-in-prod")
_JWT_ALGO = "HS256"
_ACCESS_TTL = 3600 * 24 * 7  # 7 days
_REFRESH_TTL = 3600 * 24 * 30  # 30 days


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _sign(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": _JWT_ALGO, "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = hmac.new(_JWT_SECRET.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def _verify(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        sig_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(_JWT_SECRET.encode(), sig_input, hashlib.sha256).digest()
        actual = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def create_tokens(user_id: str) -> dict:
    now = int(time.time())
    nonce = uuid.uuid4().hex[:8]
    access = _sign({"sub": user_id, "iat": now, "exp": now + _ACCESS_TTL, "type": "access", "jti": nonce})
    refresh = _sign({"sub": user_id, "iat": now, "exp": now + _REFRESH_TTL, "type": "refresh", "jti": nonce + "r"})
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


# ---- FastAPI dependency ----

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Optional[UserRow]:
    if not creds:
        return None
    payload = _verify(creds.credentials)
    if not payload or payload.get("type") != "access":
        return None
    result = await session.execute(select(UserRow).where(UserRow.id == payload["sub"]))
    return result.scalar_one_or_none()


async def require_user(user: Optional[UserRow] = Depends(get_current_user)) -> UserRow:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


# ---- Request/Response models ----

def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Validate a refresh token and issue a new access token."""
    payload = _verify(refresh_token)
    if not payload or payload.get("type") != "refresh":
        return None
    user_id = payload["sub"]
    now = int(time.time())
    nonce = uuid.uuid4().hex[:8]
    access = _sign({"sub": user_id, "iat": now, "exp": now + _ACCESS_TTL, "type": "access", "jti": nonce})
    return {"access_token": access, "token_type": "bearer"}


class SignUpRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str
