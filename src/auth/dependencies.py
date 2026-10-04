"""
FastAPI dependencies for authentication and RBAC.

Usage in routes:
    @router.get("/me")
    async def me(current_user: User = Depends(get_current_user)):
        ...

    @router.delete("/secret")
    async def secret(current_user: User = Depends(require_role(UserRole.TENANT_ADMIN))):
        ...
"""

from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db, set_tenant_context
from src.models.models import User, UserRole


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    claims = getattr(request.state, "claims", None)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = claims["sub"]
    tenant_id: str | None = claims.get("tenant_id")

    # Set Postgres session variable so RLS kicks in for this request
    if tenant_id:
        await set_tenant_context(db, tenant_id)

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_role(*roles: UserRole) -> Callable:
    """Return a dependency that enforces one of the given roles."""

    async def _dep(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in roles]}",
            )
        return current_user

    return _dep
