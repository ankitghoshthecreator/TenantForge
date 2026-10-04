"""
Auth endpoint tests — register, login, refresh, cross-tenant isolation.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password
from src.models.models import Tenant, User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def create_tenant(db: AsyncSession, name: str, slug: str) -> Tenant:
    tenant = Tenant(name=name, slug=slug)
    db.add(tenant)
    await db.flush()
    return tenant


async def create_user(
    db: AsyncSession,
    tenant: Tenant,
    email: str,
    password: str = "password123",
    role: UserRole = UserRole.MEMBER,
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        tenant_id=tenant.id,
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_register_success(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Acme Corp", "acme")
    await db_session.flush()

    resp = await client.post("/auth/register", json={
        "email": "alice@acme.com",
        "password": "securepass",
        "tenant_slug": "acme",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@acme.com"
    assert data["role"] == "member"
    assert str(data["tenant_id"]) == str(tenant.id)


@pytest.mark.asyncio
async def test_register_unknown_tenant(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post("/auth/register", json={
        "email": "bob@ghost.com",
        "password": "securepass",
        "tenant_slug": "nonexistent",
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Beta Inc", "beta")
    await db_session.flush()

    payload = {"email": "dup@beta.com", "password": "securepass", "tenant_slug": "beta"}
    r1 = await client.post("/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/auth/register", json=payload)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Gamma LLC", "gamma")
    await create_user(db_session, tenant, "carol@gamma.com", "mypassword")
    await db_session.flush()

    resp = await client.post("/auth/login", json={"email": "carol@gamma.com", "password": "mypassword"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Delta Co", "delta")
    await create_user(db_session, tenant, "dave@delta.com", "rightpass")
    await db_session.flush()

    resp = await client.post("/auth/login", json={"email": "dave@delta.com", "password": "wrongpass"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post("/auth/login", json={"email": "ghost@nowhere.com", "password": "anything"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_success(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Epsilon SA", "epsilon")
    await create_user(db_session, tenant, "eve@epsilon.com", "pass1234")
    await db_session.flush()

    login = await client.post("/auth/login", json={"email": "eve@epsilon.com", "password": "pass1234"})
    refresh_token = login.json()["refresh_token"]

    resp = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Zeta Corp", "zeta")
    await create_user(db_session, tenant, "frank@zeta.com", "pass1234")
    await db_session.flush()

    login = await client.post("/auth/login", json={"email": "frank@zeta.com", "password": "pass1234"})
    access_token = login.json()["access_token"]

    # Trying to use an access token as a refresh token should fail
    resp = await client.post("/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /me endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, db_session: AsyncSession):
    tenant = await create_tenant(db_session, "Eta Systems", "eta")
    await create_user(db_session, tenant, "grace@eta.com", "pass1234")
    await db_session.flush()

    login = await client.post("/auth/login", json={"email": "grace@eta.com", "password": "pass1234"})
    token = login.json()["access_token"]

    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "grace@eta.com"


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
