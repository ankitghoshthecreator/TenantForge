"""
pytest configuration + async test fixtures.

Uses an in-memory SQLite-compatible approach via a test Postgres DB.
For CI, spin up a Postgres container via docker-compose before running tests.
"""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text

from src.db.session import Base, get_db
from src.main import app

# ---------------------------------------------------------------------------
# Test DB URL — override via env if needed
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "postgresql+asyncpg://tenantforge:tenantforge_secret@localhost:5432/tenantforge_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Apply RLS policies (mirrors the migration)
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.execute(text("ALTER TABLE users ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text("ALTER TABLE users FORCE ROW LEVEL SECURITY"))
        await conn.execute(text("""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = 'users' AND policyname = 'tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON users
                USING (
                    tenant_id::text = current_setting('app.current_tenant_id', true)
                    OR tenant_id IS NULL
                    OR current_setting('app.current_tenant_id', true) = ''
                );
              END IF;
            END$$;
        """))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    AsyncTestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncTestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
