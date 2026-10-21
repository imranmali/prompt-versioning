# Design: Delivery pipeline

## Context

The service is a stateless container that needs a PostgreSQL URL and an optional bootstrap admin key.

## Goals / Non-Goals

**Goals:** fast PR feedback (parallel jobs, uv cache), identical artifact from CI to production, zero-downtime
rolling deploys. **Non-Goals:** environment provisioning.

## Decisions

- **uv + lockfile** for reproducible, fast installs in CI and Docker (`uv sync --frozen`).
- **Separate CI jobs** (`lint`, `test` matrix, `test-postgres`, `migrations`, `openspec`, `docker`, `audit`) so failures
  are attributable; a final `ci-success` job aggregates them for branch protection.
- **Image**: `python:3.12-slim` multi-stage; the builder creates the venv, the runtime stage copies it and runs as UID
  10001 with `uvicorn` workers via `promptlab serve`. Tags: `sha-<short>`, `latest` on main, semver on tags.
- **Deploy**: migrations run as a Kubernetes Job before the Deployment rollout (`kubectl apply -k`, wait for Job,
  then `kubectl rollout status`). Readiness probe on `/readyz`, liveness on `/healthz`; HPA scales on CPU 70%;
  PDB keeps at least one pod during voluntary disruptions. The deploy job is skipped when `KUBE_CONFIG` is absent.

## Risks / Trade-offs

- [Vulnerability audit can fail on newly published advisories unrelated to a PR] → audit runs on schedule as well and
  failures point at the dependency to bump; Dependabot keeps pins fresh.
- [Running migrations before rollout requires backward-compatible migrations] → documented in CONTRIBUTING.
