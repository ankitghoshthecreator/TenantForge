# TenantForge — Implementation Plan

> **5 independent, incrementally deliverable parts.**
> Each part is self-contained: it can be reviewed, tested, and merged without depending on the next part being done.

---

## Part 1 — Project Foundation & Auth/RBAC

**What it covers**
- Repository scaffold (FastAPI app, Docker Compose, project layout)
- PostgreSQL setup with a `tenants` table and Row-Level Security policies
- JWT-based authentication (register / login / refresh)
- Per-tenant RBAC roles: `tenant_admin`, `member`, `read_only`
- Tenant-context middleware that reads `tenant_id` from the JWT and sets a Postgres session variable so RLS fires automatically on every query

**Why this is Part 1**
Auth and tenant context are the load-bearing wall of the whole system. Every other part (flags, audit log, provisioning, infra) needs a real `tenant_id` and a working auth token to operate. By finishing this first, every subsequent part can be built and tested in isolation with real JWT tokens and real RLS enforcement.

**Implementation approach**
1. `docker-compose.yml` — Postgres 16 + Redis + FastAPI container wired together
2. `alembic` migrations:
   - `tenants(id UUID PK, name, slug, created_at, is_deleted, deleted_at)`
   - `users(id, tenant_id FK, email, hashed_password, role, created_at)`
   - Enable `pgcrypto` extension; write RLS policies on `users` keyed to `app.current_tenant_id` session variable
3. `src/auth/` — `/register`, `/login`, `/refresh` endpoints using `python-jose` for JWT signing
4. `src/middleware/tenant_context.py` — FastAPI middleware that decodes the JWT, extracts `tenant_id`, and runs `SET app.current_tenant_id = '<uuid>'` before every DB call
5. Unit tests: login happy path, wrong password, cross-tenant token rejected by RLS

---

## Part 2 — Tenant Provisioning API

**What it covers**
- Single-call tenant onboarding: `POST /admin/tenants`
- Creates tenant record, seeds default RBAC config, sends first-admin invite (email stub)
- Soft-delete with grace period: `DELETE /admin/tenants/{id}` marks `is_deleted`, schedules archival
- Data archival job: archives tenant rows to S3 (or local minio in dev) after grace period
- Super-admin role that sits outside tenant scope and can manage tenants

**Why this is Part 2**
With auth working (Part 1), we now need a way to actually create and tear down tenants. This is the operational backbone — without it, all other features have no tenants to act on.

**Implementation approach**
1. `src/provisioning/router.py` — REST endpoints behind a `super_admin` guard
2. `src/provisioning/service.py` — orchestrates: create tenant row → create first-admin user → enqueue welcome email task
3. Soft-delete: add `is_deleted BOOLEAN DEFAULT FALSE`, `deleted_at TIMESTAMPTZ`, `grace_period_days INT DEFAULT 30` to `tenants`
4. Background archival: Celery (or ARQ with Redis) scheduled task that queries expired-grace tenants and streams their rows to S3/MinIO as JSON, then hard-deletes
5. Integration tests: provision a tenant, verify admin user exists, soft-delete, verify rows still present, simulate grace expiry, verify archival

---

## Part 3 — Feature Flag Service

**What it covers**
- Per-tenant feature flags stored in Redis
- Admin API: create / update / delete / toggle flags per tenant
- In-request flag lookup with sub-millisecond Redis GET
- Fallback: if Redis is unavailable, serve last-known-good flags from a local in-process cache; features default to **off**
- Flag types: boolean on/off; percentage rollout (0-100); allowlist of tenant UUIDs

**Why this is Part 3**
Feature flags are the "deploy without deploying" capability. They depend on tenants existing (Part 2) and auth working (Part 1), but are completely decoupled from provisioning logic. They can be iterated on independently.

**Implementation approach**
1. Redis key schema: `ff:{tenant_id}:{flag_name}` -> JSON blob `{"enabled": bool, "type": "boolean"|"percentage"|"allowlist", "value": ...}`
2. `src/flags/service.py` — `get_flag(tenant_id, flag_name)` with a local `TTLCache` (cachetools) as L1; Redis as L2; hardcoded-off as fallback
3. `src/flags/router.py` — CRUD endpoints; only `tenant_admin` or `super_admin` can write
4. `src/flags/dependency.py` — FastAPI `Depends(require_flag("new_dashboard"))` decorator for route-level flag gating
5. Tests: flag on -> route accessible, flag off -> 403, Redis down -> fallback to cache, fallback expired -> default off

---

## Part 4 — Audit Log

**What it covers**
- Every write operation (create/update/delete) logged: `who`, `what`, `when`, `tenant_id`, `resource_type`, `resource_id`, `diff`
- Append-only table (no UPDATE/DELETE ever issued by app; enforced by a Postgres trigger that raises exception on UPDATE/DELETE)
- Query API: paginated, filterable by `tenant_id`, `actor_id`, `resource_type`, date range
- Async logging so it never slows the main request path

**Why this is Part 4**
Audit logging touches every other subsystem but only as a side-effect writer. It's cleanest to build after the core data flows (Parts 1-3) are settled, so we know what events actually need to be logged.

**Implementation approach**
1. Migration: `audit_logs(id UUID, tenant_id, actor_id, action ENUM, resource_type, resource_id UUID, diff JSONB, created_at TIMESTAMPTZ)`
2. Postgres trigger: `BEFORE UPDATE OR DELETE ON audit_logs -> RAISE EXCEPTION 'audit log is immutable'`
3. `src/audit/service.py` — `log_event(...)` enqueues to Redis stream (XADD); a consumer group worker reads and inserts into Postgres
4. `src/audit/middleware.py` — FastAPI middleware that injects `audit_logger` into request state; individual route handlers call it explicitly (no magic monkey-patching)
5. `src/audit/router.py` — paginated GET with filters, scoped to `tenant_id` from JWT (tenant can only query their own logs; super-admin can query all)
6. Tests: write op -> log entry exists, UPDATE on audit_log -> exception, cross-tenant query blocked by RLS

---

## Part 5 — Infrastructure as Code & CI/CD

**What it covers**
- Terraform modules: AWS ECS Fargate (app), RDS Postgres, ElastiCache Redis, S3, CloudFront
- One-command new environment: `terraform apply -var-file=staging.tfvars`
- GitHub Actions pipeline: lint -> test -> build Docker image -> push to ECR -> deploy to ECS on merge to `main`
- Per-tenant rate limiting via Redis token-bucket (noisy-neighbor protection)
- Health-check and readiness endpoints for ECS target group

**Why this is Part 5**
Infrastructure wraps everything. It makes no sense to Terraform-ify a system that isn't fully built. Part 5 is the "productionize it" layer — it takes the working local Docker Compose system and makes it cloud-deployable and CI-guarded.

**Implementation approach**
1. `infra/modules/` — reusable Terraform modules for `ecs_service`, `rds`, `elasticache`, `s3_bucket`, `cloudfront`
2. `infra/envs/staging/` and `infra/envs/prod/` — environment-specific tfvars; state stored in S3 + DynamoDB lock table
3. `src/middleware/rate_limit.py` — Redis token-bucket keyed on `tenant_id`; 429 when bucket empty; bucket size and refill rate configurable per tenant via feature flag (ties back to Part 3)
4. `GET /health` (liveness) + `GET /ready` (readiness: DB + Redis reachable)
5. `.github/workflows/ci.yml` — matrix: `[lint, test, build]` -> on success, `deploy` job uses AWS OIDC (no long-lived secrets)
6. Load test: k6 script that spins up two simulated tenants and verifies one can't starve the other's connections

---

## Dependency Map

```
Part 1 (Auth/RBAC)
    |-- Part 2 (Provisioning)   <- needs tenants + super-admin auth
    |-- Part 3 (Feature Flags)  <- needs tenant_id + auth
    |-- Part 4 (Audit Log)      <- needs auth + provisioning events to log
            |-- Part 5 (Infra)  <- wraps everything; rate-limit ties to Part 3
```

Parts 2, 3, 4 are all parallel after Part 1. Part 5 depends on all of them being feature-complete.

---

## Status

| Part | Description | Status |
|------|-------------|--------|
| 1 | Foundation, Auth & RBAC | In Progress |
| 2 | Tenant Provisioning API | Not Started |
| 3 | Feature Flag Service | Not Started |
| 4 | Audit Log | Not Started |
| 5 | Infrastructure & CI/CD | Not Started |
