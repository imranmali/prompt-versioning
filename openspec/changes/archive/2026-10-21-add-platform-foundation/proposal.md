# Proposal: Platform foundation

## Why

PromptLab needs a secure, observable, horizontally scalable service skeleton before any
prompt or experiment features can be built. Every later capability depends on a shared
persistence layer, a consistent error contract, authenticated access and operational
endpoints that orchestrators (Kubernetes, load balancers, Prometheus) can rely on.

## What Changes

- Python service skeleton (FastAPI app factory, settings from `PROMPTLAB_*` environment variables).
- Async persistence layer (SQLAlchemy 2) with the full relational schema and Alembic migrations
  that run on PostgreSQL and SQLite.
- API-key authentication with three hierarchical roles (`runtime` < `editor` < `admin`),
  hashed key storage, a bootstrap admin key and admin endpoints to issue/list/revoke keys.
- Uniform JSON error envelope and request correlation IDs.
- Liveness (`/healthz`), readiness (`/readyz`) and Prometheus metrics (`/metrics`) endpoints,
  structured JSON logging.
- Operator CLI: `promptlab serve | migrate | create-api-key`.
- Sandboxed prompt template engine shared by later changes.

## Capabilities

### New Capabilities
- `api-access-control`: API keys, roles and authorization of every `/v1` endpoint.
- `service-operations`: health/readiness/metrics endpoints, error envelope, request IDs.

### Modified Capabilities
- None.

## Out of Scope

- Prompt and experiment features (see `add-prompt-versioning`, `add-ab-testing`).
- SSO/OAuth, multi-tenant organisations and per-project key scoping.
- CI/CD and container packaging (see `add-delivery-pipeline`).

## Impact

- New code under `src/promptlab/` (config, db, models, security, errors, observability, cli).
- New dependencies: FastAPI, Uvicorn, SQLAlchemy, asyncpg, aiosqlite, Alembic,
  pydantic-settings, Jinja2, prometheus-client.
- Database: initial migration creating all tables.
