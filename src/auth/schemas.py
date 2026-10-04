"""
Pydantic schemas for auth endpoints.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str  # tenant the user is registering into

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Response bodies
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    tenant_id: Optional[UUID]

    model_config = {"from_attributes": True}
