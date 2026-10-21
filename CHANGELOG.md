# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The public contract is the HTTP API under `/v1`.

## [Unreleased]

## [1.0.0] - 2026-10-20

First stable release.

### Added

#### Platform foundation

- FastAPI service configured entirely through `PROMPTLAB_*` environment variables, with an
  async SQLAlchemy 2 persistence layer and Alembic migrations for PostgreSQL and SQLite.
- API-key authentication (`X-API-Key` or `Authorization: Bearer`) with hierarchical roles
  `runtime` < `editor` < `admin`, hashed key storage, a bootstrap admin key and endpoints to
  issue, list and revoke keys.
- Uniform JSON error envelope and per-request correlation IDs.
- Operations endpoints: liveness `/healthz`, readiness `/readyz` (database check, 503 when
  unavailable) and Prometheus `/metrics`; structured JSON logging.
- Operator CLI: `promptlab serve | migrate | downgrade | create-api-key`.

#### Prompt versioning

- Prompt registry with search and metadata updates.
- Immutable, sequentially numbered versions (template, model settings, metadata, commit
  message, author, content hash); identical re-submissions are idempotent.
- Version diffs (unified template diff, variable and model-setting changes).
- Movable deployment labels (`production`, `staging`, ...) with full audit history and
  one-call rollback.
- Sandboxed template rendering of a version or label with strict variable validation.

#### A/B testing

- Experiments with 2-10 weighted variants pinned to prompt versions, a control variant,
  traffic percentage and a `draft -> running <-> paused -> completed` lifecycle.
- Deterministic, sticky, stateless subject assignment (hash bucketing) that is identical on
  every replica.
- `resolve` endpoint returning the variant (or label fallback) version and optionally the
  rendered prompt, recording an exposure.
- Batched, idempotent ingestion of exposure, conversion and metric events.
- Per-variant statistics: conversion rate or mean, 95% confidence intervals, lift versus
  control, p-values (two-proportion z-test / Welch's t-test), sample-ratio-mismatch check and
  winner detection; completing an experiment can promote the winner to a label.

#### Delivery pipeline

- Multi-stage, non-root Docker image and a Docker Compose stack (PostgreSQL, migrations, API).
- GitHub Actions CI: ruff, mypy, tests on Python 3.12/3.13 with SQLite and on PostgreSQL,
  migration up/down check, OpenSpec validation, Docker build with smoke test and an aggregate
  `ci-success` check; separate scheduled dependency audit with pip-audit.
- GitHub Actions CD: multi-arch images on GitHub Container Registry (`sha-*`, `latest`,
  semver), GitHub Releases on tags and an opt-in Kubernetes deploy that runs migrations
  before the rollout.
- Kustomize manifests (Deployment, Service, HPA, PodDisruptionBudget, ConfigMap, migration
  Job, production overlay), Dependabot, contribution, security and deployment documentation.

[Unreleased]: https://github.com/imranmali/prompt-versioning/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/imranmali/prompt-versioning/releases/tag/v1.0.0
