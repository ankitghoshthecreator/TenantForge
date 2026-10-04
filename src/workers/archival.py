"""
ARQ background worker — tenant archival.

Runs as a separate process: `arq src.workers.archival.WorkerSettings`

Jobs:
  - archive_expired_tenants: cron every hour at :05.
      Finds all soft-deleted tenants whose grace period has expired,
      archives their data to S3, then hard-deletes them from the DB.

Startup/shutdown:
  - ctx["db_session"] is created on worker startup and reused across jobs.
  - Engine is disposed on worker shutdown to avoid connection leaks.
"""

import logging
from datetime import datetime, timedelta, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings
from src.models.models import Tenant
from src.provisioning.service import archive_and_purge_tenant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------
async def startup(ctx: dict) -> None:
    """Create a DB engine and session factory for the worker process."""
    engine = create_async_engine(settings.DATABASE_URL, pool_size=5, max_overflow=5)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    logger.info("ARQ worker started — DB pool ready")


async def shutdown(ctx: dict) -> None:
    """Dispose of the DB engine cleanly."""
    await ctx["engine"].dispose()
    logger.info("ARQ worker shut down — DB pool disposed")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
async def archive_expired_tenants(ctx: dict) -> None:
    """
    Find all tenants where:
      is_deleted = TRUE
      AND deleted_at + grace_period_days < NOW()

    For each such tenant: archive to S3 → hard-delete.
    """
    session_factory = ctx["session_factory"]
    cutoff = datetime.now(timezone.utc)

    async with session_factory() as db:
        result = await db.execute(
            select(Tenant).where(
                Tenant.is_deleted == True,  # noqa: E712
                Tenant.deleted_at.isnot(None),
            )
        )
        candidates = result.scalars().all()

    expired = [
        t for t in candidates
        if t.deleted_at + timedelta(days=t.grace_period_days) <= cutoff
    ]

    if not expired:
        logger.info("archive_expired_tenants: no expired tenants found")
        return

    logger.info(f"archive_expired_tenants: processing {len(expired)} tenant(s)")

    for tenant in expired:
        async with session_factory() as db:
            try:
                s3_key = await archive_and_purge_tenant(tenant, db)
                logger.info(f"Archived tenant {tenant.id} → {s3_key}")
            except Exception:
                logger.exception(f"Failed to archive tenant {tenant.id} — will retry next run")


# ---------------------------------------------------------------------------
# Worker settings — consumed by `arq src.workers.archival.WorkerSettings`
# ---------------------------------------------------------------------------
class WorkerSettings:
    functions = [archive_expired_tenants]
    cron_jobs = [
        # Run at :05 past every hour
        cron(archive_expired_tenants, minute=5)
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 5
    job_timeout = 300  # 5 minutes max per job
