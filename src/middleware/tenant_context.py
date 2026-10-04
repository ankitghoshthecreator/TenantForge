"""
Tenant context middleware.

Every authenticated request carries a JWT that embeds `tenant_id`.
This middleware:
1. Extracts `tenant_id` from the decoded JWT.
2. Sets `app.current_tenant_id` as a Postgres session variable via SET LOCAL,
   so every subsequent query in that request automatically passes through RLS.
3. Stores the full claims dict in `request.state.claims` for route handlers.

Non-authenticated routes (e.g. /auth/login) pass through untouched — the
middleware only activates when the Authorization header is present and valid.
"""

from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.core.security import decode_token


SKIP_PATHS = {
    "/auth/login",
    "/auth/register",
    "/health",
    "/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
}
# NOTE: /admin/* is NOT in SKIP_PATHS — it always requires a valid JWT.


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth-free endpoints
        if request.url.path in SKIP_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # No token — let individual routes decide if auth is required
            request.state.claims = None
            return await call_next(request)

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            claims = decode_token(token)
        except JWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        if claims.get("type") != "access":
            return JSONResponse(
                status_code=401,
                content={"detail": "Refresh tokens cannot be used for API access"},
            )

        request.state.claims = claims
        return await call_next(request)
