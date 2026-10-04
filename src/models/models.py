import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Enum as PgEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from src.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# RBAC roles — scoped per tenant
# ---------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"   # outside any tenant; can manage tenants
    TENANT_ADMIN = "tenant_admin" # full control within their tenant
    MEMBER = "member"             # standard user within their tenant
    READ_ONLY = "read_only"       # no write access within their tenant


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    grace_period_days = Column(sa.Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    users = relationship("User", back_populates="tenant", lazy="raise")

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug!r}>"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,  # nullable for super_admin who spans tenants
        index=True,
    )
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(PgEnum(UserRole, name="user_role"), nullable=False, default=UserRole.MEMBER)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="users", lazy="raise")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
