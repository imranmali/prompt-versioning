# Proposal: Delivery pipeline

## Why

A production-ready service needs every change verified automatically and a repeatable path from a merged
pull request to a running deployment. Without CI gates, broken code reaches `main`; without container images
and manifests, every operator invents their own deployment.

## What Changes

- GitHub Actions CI on every pull request and push to `main`: lint (ruff), format check, type check (mypy),
  tests with coverage on Python 3.12/3.13 against SQLite and PostgreSQL, migration up/down check,
  OpenSpec validation, Docker image build with container smoke test, and dependency vulnerability audit.
- GitHub Actions CD: on `main`, build and publish a multi-arch image to GitHub Container Registry tagged with
  the commit SHA and `latest`; on `v*` tags, publish semver tags and a GitHub Release; optional Kubernetes
  deploy job gated on a configured `KUBE_CONFIG` secret and a protected `production` environment.
- Multi-stage, non-root Dockerfile and `docker-compose.yml` (API + PostgreSQL) for local use.
- Kubernetes manifests (Kustomize): Deployment with probes and resource limits, Service, HPA,
  PodDisruptionBudget, ConfigMap, migration Job.
- Dependabot, pull request template, contributing, security policy and changelog.

## Capabilities

### New Capabilities
- None (tooling and packaging only; no runtime behavior changes).

### Modified Capabilities
- None.

## Out of Scope

- Helm chart, Terraform for cloud infrastructure, managed database provisioning.
- Blue/green or canary orchestration beyond Kubernetes rolling updates.

## Impact

- New `.github/`, `Dockerfile`, `docker-compose.yml`, `deploy/k8s/` and community health files.
