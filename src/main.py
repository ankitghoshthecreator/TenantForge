"""
TenantForge — FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.auth.router import router as auth_router
from src.core.config import settings
from src.db.session import AsyncSessionLocal, engine
from src.middleware.tenant_context import TenantContextMiddleware
from src.provisioning.router import router as provisioning_router


# ---------------------------------------------------------------------------
# Lifespan — run startup / shutdown tasks
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB connectivity on startup
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Config-driven, multi-tenant SaaS backend starter kit",
    lifespan=lifespan,
)

# Middleware (added in reverse order — last added runs first)
app.add_middleware(TenantContextMiddleware)

# Routers
app.include_router(auth_router)
app.include_router(provisioning_router)


# ---------------------------------------------------------------------------
# Health endpoints (used by ECS target group + readiness probes)
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Ops"])
async def health():
    """Liveness probe — app is alive."""
    return {"status": "ok"}


@app.get("/ready", tags=["Ops"])
async def ready():
    """Readiness probe — DB reachable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": str(exc)})
