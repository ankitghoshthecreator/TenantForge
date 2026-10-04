"""
Provisioning REST API — super_admin only.

Endpoints:
  POST   /admin/tenants                    — provision a new tenant
  GET    /admin/tenants                    — list all tenants (paginated)
  GET    /admin/tenants/{tenant_id}        — get a single tenant
  PATCH  /admin/tenants/{tenant_id}        — update name / grace_period
  DELETE /admin/tenants/{tenant_id}        — soft-delete
  POST   /admin/tenants/{tenant_id}/restore — undo soft-delete
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import require_role
from src.db.session import get_db
from src.models.models import UserRole
from src.provisioning import service
from src.provisioning.schemas import (
    CreateTenantRequest,
    ProvisionTenantResponse,
    TenantListResponse,
    TenantResponse,
    UpdateTenantRequest,
)

router = APIRouter(
    prefix="/admin/tenants",
    tags=["Provisioning"],
    dependencies=[Depends(require_role(UserRole.SUPER_ADMIN))],
)


# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------
@router.post("", response_model=ProvisionTenantResponse, status_code=status.HTTP_201_CREATED)
async def provision_tenant(
    body: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    One API call to onboard a new tenant:
    - Creates tenant record
    - Creates first tenant_admin user with a temporary password
    - Sends invite email (stubbed in dev)
    """
    try:
        return await service.provision_tenant(body, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@router.get("", response_model=TenantListResponse)
async def list_tenants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_tenants(db, page=page, page_size=page_size, include_deleted=include_deleted)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    tenant = await service.get_tenant(tenant_id, db)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.update_tenant(tenant_id, body, db)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------
@router.delete("/{tenant_id}", response_model=TenantResponse)
async def soft_delete_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Marks tenant as deleted with a timestamp.
    Data is retained for grace_period_days, then archived and hard-deleted
    by the background ARQ worker.
    """
    try:
        return await service.soft_delete_tenant(tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
@router.post("/{tenant_id}/restore", response_model=TenantResponse)
async def restore_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Undo a soft-delete while still within the grace period.
    Once the archival worker has run, this will return 404.
    """
    try:
        return await service.restore_tenant(tenant_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
