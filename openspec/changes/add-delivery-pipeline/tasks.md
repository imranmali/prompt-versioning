# Tasks

## 1. Containers

- [x] 1.1 Add multi-stage non-root `Dockerfile` and `.dockerignore`; verify `docker build` and `/healthz` smoke test
- [x] 1.2 Add `docker-compose.yml` with PostgreSQL and migrations; verify `docker compose config` is valid

## 2. Continuous integration

- [ ] 2.1 Add `.github/workflows/ci.yml` (lint, typecheck, tests SQLite/PostgreSQL, migrations, OpenSpec, Docker, audit); verify CI is green on the pull request
- [x] 2.2 Add Dependabot config and pull request template; verify files parse

## 3. Continuous delivery

- [x] 3.1 Add `.github/workflows/cd.yml` publishing images to GHCR and releases on tags with gated Kubernetes deploy; verify workflow syntax
- [x] 3.2 Add Kustomize manifests under `deploy/k8s/`; verify `kubectl kustomize deploy/k8s` renders

## 4. Documentation

- [ ] 4.1 Add CONTRIBUTING, SECURITY, CHANGELOG and deployment docs; verify links resolve from README

## Workflow follow-up

- Archive the change after the pull request is green.
