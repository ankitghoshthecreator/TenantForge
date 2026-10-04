"""
Provisioning service — business logic for tenant lifecycle.

Responsibilities:
  - Atomically create a tenant + first admin user
  - Send the admin invite email (stub)
  - Soft-delete with timestamping
  - Hard-delete + S3 archival (called by the ARQ worker)
"""

import json
import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import aioboto3
from botocore.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.email import EmailMessage, send_email
from src.core.security import hash_password
from src.models.models import Tenant, User, UserRole
from src.provisioning.schemas import (
    CreateTenantRequest,
    ProvisionTenantResponse,
    TenantListResponse,
    TenantResponse,
    UpdateTenantRequest,
)

logger = logging.getLogger(__name__)

_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*"


def _generate_temp_password(length: int = 16) -> str:
    """Generate a cryptographically random temporary password."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


# ---------------------------------------------------------------------------
# Provision (create)
# ---------------------------------------------------------------------------
async def provision_tenant(
    body: CreateTenantRequest,
    db: AsyncSession,
) -> ProvisionTenantResponse:
    """
    Atomically:
      1. Creates the tenant row
      2. Creates a tenant_admin user with a temp password
      3. Sends (stubs) the invite email

    Raises ValueError if slug is already taken.
    """
    # Check slug uniqueness
    existing = await db.execute(
        select(Tenant).where(Tenant.slug == body.slug)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"Slug '{body.slug}' is already taken")

    # Check admin email uniqueness
    existing_user = await db.execute(
        select(User).where(User.email == body.admin_email)
    )
    if existing_user.scalar_one_or_none() is not None:
        raise ValueError(f"Email '{body.admin_email}' is already registered")

    temp_password = _generate_temp_password()

    tenant = Tenant(
        name=body.name,
        slug=body.slug,
        grace_period_days=body.grace_period_days,
    )
    db.add(tenant)
    await db.flush()  # get tenant.id before creating the user

    admin_user = User(
        email=body.admin_email,
        hashed_password=hash_password(temp_password),
        tenant_id=tenant.id,
        role=UserRole.TENANT_ADMIN,
    )
    db.add(admin_user)
    await db.commit()
    await db.refresh(tenant)

    # Send invite email (stub in dev)
    await send_email(
        EmailMessage(
            to=body.admin_email,
            subject=f"Welcome to {body.name} on TenantForge",
            body=(
                f"Your tenant '{body.name}' has been provisioned.\n\n"
                f"Login URL: http://localhost:8000\n"
                f"Email: {body.admin_email}\n"
                f"Temporary Password: {temp_password}\n\n"
                "Please change your password on first login."
            ),
        )
    )

    return ProvisionTenantResponse(
        tenant=TenantResponse.model_validate(tenant),
        admin_email=body.admin_email,
        temporary_password=temp_password,
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
async def list_tenants(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
) -> TenantListResponse:
    query = select(Tenant)
    if not include_deleted:
        query = query.where(Tenant.is_deleted == False)  # noqa: E712

    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar_one()

    query = query.order_by(Tenant.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tenants = result.scalars().all()

    return TenantListResponse(
        items=[TenantResponse.model_validate(t) for t in tenants],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------
async def get_tenant(tenant_id: UUID, db: AsyncSession) -> Optional[Tenant]:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
async def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    db: AsyncSession,
) -> Tenant:
    tenant = await get_tenant(tenant_id, db)
    if tenant is None or tenant.is_deleted:
        raise LookupError(f"Tenant {tenant_id} not found")

    if body.name is not None:
        tenant.name = body.name
    if body.grace_period_days is not None:
        tenant.grace_period_days = body.grace_period_days

    await db.commit()
    await db.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------
async def soft_delete_tenant(tenant_id: UUID, db: AsyncSession) -> Tenant:
    tenant = await get_tenant(tenant_id, db)
    if tenant is None:
        raise LookupError(f"Tenant {tenant_id} not found")
    if tenant.is_deleted:
        raise ValueError(f"Tenant {tenant_id} is already deleted")

    tenant.is_deleted = True
    tenant.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tenant)

    logger.info(
        "Tenant soft-deleted",
        extra={"tenant_id": str(tenant_id), "grace_period_days": tenant.grace_period_days},
    )
    return tenant


# ---------------------------------------------------------------------------
# Restore (undo soft-delete before grace period expires)
# ---------------------------------------------------------------------------
async def restore_tenant(tenant_id: UUID, db: AsyncSession) -> Tenant:
    tenant = await get_tenant(tenant_id, db)
    if tenant is None:
        raise LookupError(f"Tenant {tenant_id} not found")
    if not tenant.is_deleted:
        raise ValueError(f"Tenant {tenant_id} is not deleted")

    tenant.is_deleted = False
    tenant.deleted_at = None
    await db.commit()
    await db.refresh(tenant)
    return tenant


# ---------------------------------------------------------------------------
# Hard-delete + S3 archival (called by ARQ worker)
# ---------------------------------------------------------------------------
async def archive_and_purge_tenant(tenant: Tenant, db: AsyncSession) -> str:
    """
    1. Fetch all tenant users.
    2. Write them as NDJSON to S3 / MinIO.
    3. Hard-delete the tenant (CASCADE removes users).

    Returns the S3 object key that was written.
    """
    # Collect data to archive
    users_result = await db.execute(
        select(User).where(User.tenant_id == tenant.id)
    )
    users = users_result.scalars().all()

    archive_payload = {
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "created_at": tenant.created_at.isoformat(),
            "deleted_at": tenant.deleted_at.isoformat() if tenant.deleted_at else None,
        },
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
    }

    s3_key = f"tenants/{tenant.id}/{tenant.deleted_at.strftime('%Y%m%d')}_archive.json"
    s3_body = json.dumps(archive_payload, indent=2)

    # Upload to S3 / MinIO
    session = aioboto3.Session()
    boto_kwargs = dict(
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    if settings.S3_ENDPOINT_URL:
        boto_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

    async with session.client("s3", **boto_kwargs) as s3:
        await s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=s3_body.encode(),
            ContentType="application/json",
        )

    logger.info(f"Archived tenant {tenant.id} → s3://{settings.S3_BUCKET_NAME}/{s3_key}")

    # Hard-delete — CASCADE removes users automatically
    await db.delete(tenant)
    await db.commit()

    logger.info(f"Hard-deleted tenant {tenant.id} after archival")
    return s3_key
