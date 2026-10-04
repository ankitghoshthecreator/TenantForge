"""
Seed a super_admin user.

Usage:
    python -m scripts.create_superadmin --email admin@tenantforge.io --password secret123

This is a one-time bootstrap script.  In production, run once after
`alembic upgrade head` and before starting the API server.
"""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.core.security import hash_password
from src.models.models import User, UserRole


async def create_super_admin(email: str, password: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        from sqlalchemy import select

        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"[!] User {email!r} already exists — skipping.")
            await engine.dispose()
            return

        user = User(
            email=email,
            hashed_password=hash_password(password),
            tenant_id=None,      # super_admin has no tenant
            role=UserRole.SUPER_ADMIN,
        )
        db.add(user)
        await db.commit()
        print(f"[+] Super admin created: {email}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a TenantForge super admin")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password (min 8 chars)")
    args = parser.parse_args()

    if len(args.password) < 8:
        print("Error: password must be at least 8 characters")
        raise SystemExit(1)

    asyncio.run(create_super_admin(args.email, args.password))
