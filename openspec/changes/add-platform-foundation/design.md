# Design: Platform foundation

## Context

Greenfield repository. All later changes (`add-prompt-versioning`, `add-ab-testing`) build on the
modules introduced here, so this change fixes the data model and module boundaries up front to
let those changes be implemented in parallel without touching shared files.

## Goals / Non-Goals

**Goals:**
- Stateless app instances; all state in the relational database.
- One schema that works unchanged on PostgreSQL (production) and SQLite (dev/tests).
- Module layout that lets feature work proceed in parallel.

**Non-Goals:**
- Distributed caches, message queues or background workers.
- Multi-tenancy.

## Decisions

### Stack: FastAPI + SQLAlchemy 2 async + Alembic
FastAPI gives OpenAPI docs and Pydantic v2 validation for free; async SQLAlchemy with asyncpg keeps
per-instance throughput high. Alternatives: Django (heavier, sync ORM), Flask (no native async/validation).

### Layout
```
src/promptlab/
  main.py            app factory (create_app), router registration
  config.py          Settings (pydantic-settings, PROMPTLAB_ prefix)
  db.py              engine/session factory, Base, UTCDateTime type
  models.py          all ORM models (single source of truth for the schema)
  security.py        key generation/hashing, Role, require_role() dependency
  errors.py          ApiError hierarchy + exception handlers
  observability.py   JSON logging, request-id + metrics middleware
  cache.py           bounded in-process TTL cache (optional, per instance)
  cli.py             serve | migrate | create-api-key
  migrations/        Alembic environment + versions (shipped inside the package)
  api/routes/        one router module per resource
  schemas/           Pydantic request/response models per resource
  services/          business logic, free of HTTP concerns
```
Routers stay thin: validation in `schemas`, rules in `services`, persistence via `models`.

### Data model (all ids UUID, timestamps timezone-aware UTC)
- `api_keys(id, name, prefix, key_hash UNIQUE, role, created_at, last_used_at, revoked_at)`
- `prompts(id, name UNIQUE, description, tags JSON, created_at, updated_at)`
- `prompt_versions(id, prompt_id FK, version INT, template, variables JSON, model_settings JSON,
  metadata JSON, commit_message, content_hash, created_by, created_at)`, `UNIQUE(prompt_id, version)`
- `prompt_labels(id, prompt_id FK, name, version_id FK, updated_by, updated_at)`, `UNIQUE(prompt_id, name)`
- `label_events(id, prompt_id FK, label, from_version, to_version, actor, created_at)` (audit trail)
- `experiments(id, prompt_id FK, name, description, status, salt, traffic_percent, primary_metric,
  fallback_label, winner_variant_id, started_at, ended_at, created_at, updated_at)`, `UNIQUE(prompt_id, name)`
- `experiment_variants(id, experiment_id FK, key, version_id FK, weight, is_control)`, `UNIQUE(experiment_id, key)`
- `events(id BIGINT, experiment_id FK, variant_id FK, subject_id, name, value FLOAT, event_id, created_at)`
  with indexes on `(experiment_id, name, variant_id)` and unique `(experiment_id, event_id)` for idempotency.

### API keys
Keys are `pl_<43 url-safe chars>` (256 bits). Because they are high-entropy random tokens, a
SHA-256 digest is sufficient (no slow KDF needed) and allows O(1) indexed lookup. Alternative:
bcrypt/argon2 — rejected, it would force a scan or a separate lookup id and adds latency on every call.
The bootstrap admin key is compared in constant time and never stored.

### Errors and observability
A single `ApiError(status, code, message, details)` base class; handlers translate FastAPI/Starlette
validation and HTTP errors into the same envelope. Prometheus metrics use the matched route
template (not the raw path) as a label to bound cardinality.

### Templates
Jinja2 `SandboxedEnvironment` with `StrictUndefined`: familiar `{{ variable }}` syntax, blocks
attribute access to dunder methods, and missing variables fail loudly. Variables are discovered with
`jinja2.meta.find_undeclared_variables`. Alternative: `str.format` — rejected (no conditionals/loops,
attribute access to arbitrary objects).

## Risks / Trade-offs

- [SQLite lacks some concurrency guarantees] → only used for dev/tests; CI also runs the suite on PostgreSQL.
- [In-process cache can serve stale data for up to its TTL] → TTL is short and configurable, 0 disables it.
- [SHA-256 key hashes are fast to brute force if keys were low-entropy] → keys are always 256-bit random.

## Migration Plan

Fresh install: `promptlab migrate` (Alembic `upgrade head`) before starting replicas; the Kubernetes
manifests run it as a pre-deploy Job. Rollback: redeploy the previous image; down-migrations exist.
