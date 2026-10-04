# TenantForge
### A Config-Driven, Multi-Tenant SaaS Backend Starter Kit

## 🧠 Overview

TenantForge is a production-shaped multi-tenant backend platform: tenant isolation, role-based access control, feature flags, and infrastructure-as-code deployment — the unglamorous plumbing that every real SaaS/B2B backend needs, built once and done properly.

## Problem Statement

Almost every backend job posting mentions "multi-tenant" without explaining how hard it actually is:
- Should tenants share a database with a `tenant_id` column, or get isolated schemas?
- How do you stop a bug in tenant A's code path from leaking tenant B's data?
- How do you roll out a feature to 3 pilot tenants without a full deploy?
- How do you keep infrastructure reproducible as you onboard tenant #50?

TenantForge answers all four with a working reference implementation, not just an opinion.

## ⚙️ System Design

### Tenant Isolation Strategy
```
Request → Auth (JWT, tenant_id claim)
            ↓
     Tenant Context Middleware
            ↓
   ┌────────┴────────┐
   │  Shared schema    │  Row-Level Security (PostgreSQL RLS)
   │  + tenant_id       │  enforced at the DB layer — not just
   │  on every table    │  application-layer filtering
   └────────┬────────┘
            ↓
      Business Logic
```
RLS is the key decision: even if application code forgets a `WHERE tenant_id = ?`, the database itself refuses to return another tenant's rows.

### Core Components
- **Auth & RBAC** — JWT-based auth, roles scoped per-tenant (`tenant_admin`, `member`, `read_only`)
- **Feature Flag Service** — per-tenant flags stored in Redis, checked in-request with sub-millisecond lookup, admin API to toggle without a deploy
- **Audit Log** — every write operation logged with `who/what/when/tenant`, queryable, immutable (append-only table)
- **Provisioning API** — onboarding a new tenant is one API call: creates tenant record, seeds default config, issues first admin invite
- **Infra** — Terraform-defined AWS stack (ECS Fargate, RDS Postgres, S3, CloudFront), so a new environment is `terraform apply`, not a runbook

## 🧪 Failure Handling / Edge Cases
- **Tenant deletion** — soft-delete with a grace period; data is archived to S3, not immediately destroyed (compliance-friendly)
- **Cross-tenant data leak attempt** — covered by both application-layer checks *and* RLS as defense-in-depth; test suite includes explicit "tenant A tries to read tenant B's data" cases
- **Feature flag service down** — falls back to last-known-good flags cached locally per instance, fails safe (features default off, not on)
- **Noisy-neighbor tenant** — per-tenant rate limiting and connection pool caps prevent one tenant from starving DB connections for others

## Tech Stack
- **Backend:** Python, FastAPI
- **Database:** PostgreSQL with Row-Level Security
- **Cache/flags:** Redis
- **Frontend:** React, TypeScript (tenant admin dashboard)
- **Infra:** Docker, AWS (ECS Fargate, RDS, S3, CloudFront), Terraform
- **CI/CD:** GitHub Actions — lint, test, build, deploy on merge to main

## 🔑 Key Features
- Database-enforced tenant isolation (RLS), not just application-layer trust
- Feature flags with instant per-tenant rollout/rollback, no redeploy
- Full audit trail for compliance-style requirements
- One-call tenant provisioning
- Infrastructure fully defined as code — reproducible environments

## 🚀 Future Improvements
- Optional schema-per-tenant mode for enterprise tenants needing hard isolation
- Usage-based billing hooks (metering per tenant)
- SSO/SAML support for enterprise tenants

## 📚 Why This Project Matters for SDE Roles
"Multi-tenant" is one of the most-repeated words in backend JDs and one of the least-demonstrated skills in student portfolios, because most people just add a `tenant_id` column and call it done. This project proves you understand *why* that's not enough — which is exactly the kind of depth Edgro's "configurable, multi-tenant systems" bullet is fishing for.

---
*This is a design spec / project blueprint — an implementation plan, not a claim of a built system, until executed.*
