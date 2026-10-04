"""
Integration tests for the Tenant Provisioning API.

Tests use the same conftest fixtures as auth tests (real Postgres + RLS).
A super_admin JWT is constructed directly via create_access_token so we
don't depend on a bootstrap script to be run before tests.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password
from src.models.models import Tenant, User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _super_admin_headers(user: User) -> dict:
    """Build Authorization header for a super_admin user."""
    token = create_access_token(
        user_id=user.id,
        tenant_id=None,
        role=UserRole.SUPER_ADMIN.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _tenant_admin_headers(user: User) -> dict:
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=UserRole.TENANT_ADMIN.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def super_admin(db_session: AsyncSession) -> User:
    user = User(
        email="root@tenantforge.io",
        hashed_password=hash_password("superpass"),
        tenant_id=None,
        role=UserRole.SUPER_ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Provision tenant
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_provision_tenant_success(client: AsyncClient, super_admin: User, db_session: AsyncSession):
    resp = await client.post(
        "/admin/tenants",
        json={
            "name": "Acme Corporation",
            "admin_email": "admin@acme.com",
        },
        headers=_super_admin_headers(super_admin),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tenant"]["name"] == "Acme Corporation"
    assert data["tenant"]["slug"] == "acme-corporation"
    assert data["admin_email"] == "admin@acme.com"
    assert len(data["temporary_password"]) == 16

    # Verify admin user was created in DB
    result = await db_session.execute(
        select(User).where(User.email == "admin@acme.com")
    )
    admin = result.scalar_one_or_none()
    assert admin is not None
    assert admin.role == UserRole.TENANT_ADMIN


@pytest.mark.asyncio
async def test_provision_tenant_custom_slug(client: AsyncClient, super_admin: User):
    resp = await client.post(
        "/admin/tenants",
        json={
            "name": "Beta Inc",
            "slug": "my-custom-slug",
            "admin_email": "admin@beta.com",
        },
        headers=_super_admin_headers(super_admin),
    )
    assert resp.status_code == 201
    assert resp.json()["tenant"]["slug"] == "my-custom-slug"


@pytest.mark.asyncio
async def test_provision_tenant_duplicate_slug(client: AsyncClient, super_admin: User):
    payload = {"name": "Gamma", "admin_email": "a@gamma.com"}
    r1 = await client.post("/admin/tenants", json=payload, headers=_super_admin_headers(super_admin))
    assert r1.status_code == 201

    payload2 = {"name": "Gamma", "admin_email": "b@gamma.com"}  # same slug
    r2 = await client.post("/admin/tenants", json=payload2, headers=_super_admin_headers(super_admin))
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_provision_tenant_requires_super_admin(client: AsyncClient, db_session: AsyncSession):
    """Tenant admins cannot provision new tenants."""
    tenant = Tenant(name="Delta", slug="delta")
    db_session.add(tenant)
    await db_session.flush()

    ta = User(
        email="ta@delta.com",
        hashed_password=hash_password("pw"),
        tenant_id=tenant.id,
        role=UserRole.TENANT_ADMIN,
    )
    db_session.add(ta)
    await db_session.flush()

    resp = await client.post(
        "/admin/tenants",
        json={"name": "New Tenant", "admin_email": "x@new.com"},
        headers=_tenant_admin_headers(ta),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# List tenants
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_tenants(client: AsyncClient, super_admin: User):
    # Provision two tenants
    for i in range(2):
        await client.post(
            "/admin/tenants",
            json={"name": f"List Tenant {i}", "admin_email": f"admin{i}@list.com"},
            headers=_super_admin_headers(super_admin),
        )

    resp = await client.get("/admin/tenants", headers=_super_admin_headers(super_admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_list_tenants_pagination(client: AsyncClient, super_admin: User):
    resp = await client.get(
        "/admin/tenants?page=1&page_size=1",
        headers=_super_admin_headers(super_admin),
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) <= 1


# ---------------------------------------------------------------------------
# Get single tenant
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tenant(client: AsyncClient, super_admin: User):
    create_resp = await client.post(
        "/admin/tenants",
        json={"name": "Get Me", "admin_email": "admin@getme.com"},
        headers=_super_admin_headers(super_admin),
    )
    tenant_id = create_resp.json()["tenant"]["id"]

    resp = await client.get(f"/admin/tenants/{tenant_id}", headers=_super_admin_headers(super_admin))
    assert resp.status_code == 200
    assert resp.json()["id"] == tenant_id


@pytest.mark.asyncio
async def test_get_tenant_not_found(client: AsyncClient, super_admin: User):
    resp = await client.get(
        "/admin/tenants/00000000-0000-0000-0000-000000000000",
        headers=_super_admin_headers(super_admin),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update tenant
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_tenant(client: AsyncClient, super_admin: User):
    create_resp = await client.post(
        "/admin/tenants",
        json={"name": "Old Name", "admin_email": "admin@oldname.com"},
        headers=_super_admin_headers(super_admin),
    )
    tenant_id = create_resp.json()["tenant"]["id"]

    resp = await client.patch(
        f"/admin/tenants/{tenant_id}",
        json={"name": "New Name", "grace_period_days": 60},
        headers=_super_admin_headers(super_admin),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["grace_period_days"] == 60


# ---------------------------------------------------------------------------
# Soft-delete + restore
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_soft_delete_tenant(client: AsyncClient, super_admin: User):
    create_resp = await client.post(
        "/admin/tenants",
        json={"name": "Delete Me", "admin_email": "admin@deleteme.com"},
        headers=_super_admin_headers(super_admin),
    )
    tenant_id = create_resp.json()["tenant"]["id"]

    del_resp = await client.delete(
        f"/admin/tenants/{tenant_id}",
        headers=_super_admin_headers(super_admin),
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["is_deleted"] is True
    assert del_resp.json()["deleted_at"] is not None

    # Not listed by default (include_deleted=False)
    list_resp = await client.get("/admin/tenants", headers=_super_admin_headers(super_admin))
    ids = [t["id"] for t in list_resp.json()["items"]]
    assert tenant_id not in ids

    # But visible with include_deleted=true
    list_del_resp = await client.get(
        "/admin/tenants?include_deleted=true",
        headers=_super_admin_headers(super_admin),
    )
    ids_with_deleted = [t["id"] for t in list_del_resp.json()["items"]]
    assert tenant_id in ids_with_deleted


@pytest.mark.asyncio
async def test_double_delete_conflict(client: AsyncClient, super_admin: User):
    create_resp = await client.post(
        "/admin/tenants",
        json={"name": "Double Delete", "admin_email": "admin@doubledelete.com"},
        headers=_super_admin_headers(super_admin),
    )
    tenant_id = create_resp.json()["tenant"]["id"]

    await client.delete(f"/admin/tenants/{tenant_id}", headers=_super_admin_headers(super_admin))
    resp2 = await client.delete(f"/admin/tenants/{tenant_id}", headers=_super_admin_headers(super_admin))
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_restore_tenant(client: AsyncClient, super_admin: User):
    create_resp = await client.post(
        "/admin/tenants",
        json={"name": "Restore Me", "admin_email": "admin@restoreme.com"},
        headers=_super_admin_headers(super_admin),
    )
    tenant_id = create_resp.json()["tenant"]["id"]

    await client.delete(f"/admin/tenants/{tenant_id}", headers=_super_admin_headers(super_admin))

    restore_resp = await client.post(
        f"/admin/tenants/{tenant_id}/restore",
        headers=_super_admin_headers(super_admin),
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["is_deleted"] is False
    assert restore_resp.json()["deleted_at"] is None
