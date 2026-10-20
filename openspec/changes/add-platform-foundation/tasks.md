# Tasks

## 1. Project scaffolding

- [ ] 1.1 Create `pyproject.toml` (hatchling, ruff, mypy, pytest config) and `uv.lock`; verify `uv sync` succeeds
- [ ] 1.2 Add `Makefile` targets (install, lint, format, typecheck, test, run, migrate); verify `make lint` runs

## 2. Core service

- [ ] 2.1 Implement `config.py` settings with `PROMPTLAB_*` env vars; verify settings unit tests
- [ ] 2.2 Implement `db.py` and `models.py` with the full schema; verify tables create on SQLite and PostgreSQL
- [ ] 2.3 Add Alembic environment and initial migration inside the package; verify `promptlab migrate` creates the schema
- [ ] 2.4 Implement error envelope and handlers; verify error tests for 404/422/500
- [ ] 2.5 Implement request-id, JSON logging and Prometheus middleware plus `/healthz`, `/readyz`, `/metrics`; verify operations tests

## 3. Access control

- [ ] 3.1 Implement key generation/hashing, roles and `require_role` dependency; verify auth tests (401/403, bearer, revoked)
- [ ] 3.2 Implement `/v1/api-keys` create/list/revoke; verify API key tests
- [ ] 3.3 Implement `promptlab create-api-key` CLI; verify CLI test

## 4. Shared building blocks

- [ ] 4.1 Implement sandboxed template rendering and variable extraction; verify templating unit tests
- [ ] 4.2 Implement bounded TTL cache; verify cache unit tests
- [ ] 4.3 Register empty routers for prompts, experiments and events; verify app starts and OpenAPI renders

## Workflow follow-up

- Archive the change after the pull request is green.
