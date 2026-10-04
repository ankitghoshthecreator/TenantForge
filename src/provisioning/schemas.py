"""
Pydantic schemas for the Tenant Provisioning API.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator
from slugify import slugify


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class CreateTenantRequest(BaseModel):
    """
    Single-call tenant onboarding payload.
    Creates the tenant + seeds a tenant_admin user in one transaction.
    """

    name: str = Field(..., min_length=2, max_length=255, description="Human-readable tenant name")
    slug: Optional[str] = Field(
        None,
        description="URL-safe identifier. Auto-derived from name if omitted.",
    )
    admin_email: EmailStr = Field(..., description="Email address for the first tenant admin")
    grace_period_days: int = Field(
        30,
        ge=1,
        le=365,
        description="Days to retain data after soft-delete before archival",
    )

    @field_validator("slug", mode="before")
    @classmethod
    def derive_slug(cls, v: Optional[str], info) -> str:
        if v:
            return slugify(v)
        name = info.data.get("name", "")
        return slugify(name)


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    grace_period_days: Optional[int] = Field(None, ge=1, le=365)


# ---------------------------------------------------------------------------
# Response bodies
# ---------------------------------------------------------------------------
class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    is_deleted: bool
    deleted_at: Optional[datetime]
    grace_period_days: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ProvisionTenantResponse(BaseModel):
    """
    Returned from POST /admin/tenants.
    Includes a temporary password that is also emailed to the admin.
    In production the password would NOT be in the API response —
    only delivered via email. Included here for developer convenience.
    """

    tenant: TenantResponse
    admin_email: str
    temporary_password: str
    message: str = "Tenant provisioned. Admin invite email sent (stub in dev)."


class TenantListResponse(BaseModel):
    items: list[TenantResponse]
    total: int
    page: int
    page_size: int
