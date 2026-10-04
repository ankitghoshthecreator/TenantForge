"""
JWT helpers — sign, verify, and decode access + refresh tokens.

Design decisions:
- Access tokens are short-lived (default 30 min); refresh tokens are long-lived (7 days).
- Both embed `sub` (user id), `tenant_id`, and `role` so downstream middleware
  never needs a DB round-trip to check authorization basics.
- Refresh tokens carry a `type: refresh` claim so they can't be used as access tokens.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.config import settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------
def _make_token(
    payload: dict,
    expires_delta: timedelta,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {**payload, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: UUID, tenant_id: Optional[UUID], role: str) -> str:
    return _make_token(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "role": role,
            "type": "access",
        },
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: UUID, tenant_id: Optional[UUID], role: str) -> str:
    return _make_token(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "role": role,
            "type": "refresh",
        },
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------
def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.  Raises JWTError on invalid/expired tokens.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
