# Deploying PromptLab

PromptLab is a single stateless HTTP container backed by PostgreSQL. Any number of identical
replicas can run behind a load balancer: experiment assignment is deterministic (hash based),
and the only in-process state is an optional, short-lived resolve cache.

- [Container image](#container-image)
- [Docker Compose](#docker-compose)
- [Kubernetes](#kubernetes)
- [Continuous delivery](#continuous-delivery)
- [Configuration](#configuration)
- [Scaling](#scaling)
- [Migrations and rollbacks](#migrations-and-rollbacks)
- [Observability](#observability)
- [Backups](#backups)

## Container image

Images are published to GitHub Container Registry for `linux/amd64` and `linux/arm64`:

| Tag                 | When                                       |
| ------------------- | ------------------------------------------ |
| `sha-<short sha>`   | every push to `main` and every release tag |
| `latest`            | latest commit on `main`                    |
| `X.Y.Z`, `X.Y`      | release tags `vX.Y.Z`                      |

```bash
docker pull ghcr.io/imranmali/prompt-versioning:1.0.0
```

Pin production deployments to a version tag or, better, a digest (`@sha256:...`).

The image runs as UID/GID `10001`, listens on port `8000`, and its entrypoint is the
`promptlab` CLI (default command `serve --host 0.0.0.0 --port 8000`):

```bash
# 1. Apply migrations (idempotent; run before starting new versions)
docker run --rm -e PROMPTLAB_DATABASE_URL="postgresql+asyncpg://user:pass@db:5432/promptlab" \
  ghcr.io/imranmali/prompt-versioning:1.0.0 migrate

# 2. Start the API (append --workers N for more uvicorn processes)
docker run -d -p 8000:8000 \
  -e PROMPTLAB_DATABASE_URL="postgresql+asyncpg://user:pass@db:5432/promptlab" \
  -e PROMPTLAB_BOOTSTRAP_ADMIN_KEY="$(openssl rand -hex 32)" \
  ghcr.io/imranmali/prompt-versioning:1.0.0

# 3. Issue a named admin key, then drop the bootstrap key from the environment
docker run --rm -e PROMPTLAB_DATABASE_URL=... ghcr.io/imranmali/prompt-versioning:1.0.0 \
  create-api-key --name ops-admin --role admin
```

The image has a Docker `HEALTHCHECK` on `/healthz`. The root filesystem can be mounted
read-only as long as `/tmp` is writable (the Kubernetes manifests do exactly that). Build it
yourself with `make docker-build` or `docker build -t promptlab .`.

## Docker Compose

`docker-compose.yml` runs PostgreSQL 16, a one-shot `migrate` service and the API (which only
starts after migrations completed successfully):

```bash
docker compose up --build -d --wait     # or: make compose-up
curl localhost:8000/readyz
curl -H "X-API-Key: dev-admin-key-change-me" localhost:8000/v1/api-keys
docker compose down -v                  # stop and delete the database volume
```

Override `PROMPTLAB_BOOTSTRAP_ADMIN_KEY`, `PROMPTLAB_PORT` (host port, default 8000),
`POSTGRES_PORT` (host port, default 5432) and `WEB_CONCURRENCY` (default 1) through the shell
or a `.env` file. The Compose credentials are for local use only.

## Kubernetes

Manifests live in `deploy/k8s` (Kustomize):

```text
deploy/k8s/
├── base/                    # namespace, ConfigMap, Deployment, Service, HPA, PDB
│   └── secret.example.yaml  # documentation only, never applied
├── jobs/                    # promptlab-migrate Job (applied separately, before the rollout)
└── overlays/production/     # production patches (resources, HPA bounds, config)
```

What the base provides:

- **Deployment** `promptlab`: rolling updates with `maxUnavailable: 0` / `maxSurge: 1`;
  startup and liveness probes on `/healthz`, readiness on `/readyz` (pods leave the Service
  while the database is unreachable); requests 100m CPU / 256Mi, limits 1 CPU / 512Mi; non-root
  UID 10001, read-only root filesystem with an `emptyDir` at `/tmp`, no privilege escalation, all
  capabilities dropped, `RuntimeDefault` seccomp; spread across zones and nodes; a 5 s `preStop`
  delay and 30 s grace period for connection draining; Prometheus scrape annotations.
- **Service** `promptlab`: ClusterIP, port 80 to container port 8000. Expose it with your
  ingress controller or Gateway and terminate TLS there.
- **HorizontalPodAutoscaler**: 3 to 20 replicas at 70% CPU. It owns the replica count, which
  is why the Deployment does not set `spec.replicas`.
- **PodDisruptionBudget**: at most one API pod is evicted at a time during drains.
- **Namespace** `promptlab` with the `restricted` Pod Security Standard enforced.

### First deployment

```bash
# 1. Namespace and secret (keep real secrets out of git)
kubectl apply -f deploy/k8s/base/namespace.yaml
kubectl -n promptlab create secret generic promptlab-secrets \
  --from-literal=PROMPTLAB_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/promptlab' \
  --from-literal=PROMPTLAB_BOOTSTRAP_ADMIN_KEY="$(openssl rand -hex 32)"

# 2. Pin the image you want to run
(cd deploy/k8s/overlays/production && kustomize edit set image \
  ghcr.io/imranmali/prompt-versioning=ghcr.io/imranmali/prompt-versioning:1.0.0)
(cd deploy/k8s/jobs && kustomize edit set image \
  ghcr.io/imranmali/prompt-versioning=ghcr.io/imranmali/prompt-versioning:1.0.0)

# 3. Migrate, then roll out
kubectl -n promptlab delete job promptlab-migrate --ignore-not-found
kubectl apply -k deploy/k8s/jobs
kubectl -n promptlab wait --for=condition=complete job/promptlab-migrate --timeout=300s
kubectl apply -k deploy/k8s/overlays/production
kubectl -n promptlab rollout status deployment/promptlab --timeout=300s
```

Preview the rendered manifests with `kubectl kustomize deploy/k8s/overlays/production`.
Settings in the ConfigMap are read at start-up; after changing them outside a deploy run
`kubectl -n promptlab rollout restart deployment/promptlab`.

## Continuous delivery

`.github/workflows/cd.yml` runs on pushes to `main`, on `v*.*.*` tags and on demand:

1. **publish** builds the multi-arch image, pushes the tags above (with SBOM and provenance)
   and, for tags, creates a GitHub Release with generated notes.
2. **deploy** (optional) pins the just-published digest in `overlays/production` and `jobs`,
   re-creates the migration Job and waits for it (stopping if it fails), then applies the
   overlay and waits for `kubectl rollout status`.

To enable deployment:

1. Create a GitHub **environment** named `production` (Settings > Environments) and add
   required reviewers and/or a deployment-branch rule (`main` and `v*` tags).
2. Add the environment secret **`KUBE_CONFIG`**: a kubeconfig (plain YAML or base64) for a
   service account allowed to manage Deployments, Services, ConfigMaps, HPAs, PDBs and Jobs in
   the `promptlab` namespace (and to create the namespace on the first run).
3. Set the repository **variable** `DEPLOY_ENABLED` to `true`. While it is unset the deploy job
   is skipped and CD only publishes images.

CD runs in parallel with CI on `main`; this is safe because `main` only receives pull requests
that already passed the required `ci-success` check.

## Configuration

All settings are environment variables with the `PROMPTLAB_` prefix (a `.env` file in the
working directory is also read). Defaults come from `src/promptlab/config.py`.

| Variable                              | Default                              | Description |
| ------------------------------------- | ------------------------------------ | ----------- |
| `PROMPTLAB_ENVIRONMENT`               | `development`                        | `development`, `test` or `production`. |
| `PROMPTLAB_DATABASE_URL`              | `sqlite+aiosqlite:///./promptlab.db` | SQLAlchemy async URL. Use `postgresql+asyncpg://user:pass@host:5432/db` in production. **Secret.** |
| `PROMPTLAB_DB_POOL_SIZE`              | `10`                                 | Persistent connections per worker process (PostgreSQL). |
| `PROMPTLAB_DB_MAX_OVERFLOW`           | `20`                                 | Extra burst connections per worker process. |
| `PROMPTLAB_DB_POOL_RECYCLE_SECONDS`   | `1800`                               | Recycle connections older than this (`-1` disables). |
| `PROMPTLAB_DB_ECHO`                   | `false`                              | Log every SQL statement (debugging only). |
| `PROMPTLAB_AUTH_ENABLED`              | `true`                               | `false` treats every request as admin. Never disable in shared environments. |
| `PROMPTLAB_BOOTSTRAP_ADMIN_KEY`       | unset                                | Break-glass admin API key. **Secret.** Remove after creating named keys. |
| `PROMPTLAB_LOG_LEVEL`                 | `INFO`                               | Python log level. |
| `PROMPTLAB_LOG_JSON`                  | `true`                               | Structured JSON logs (one object per line). |
| `PROMPTLAB_METRICS_ENABLED`           | `true`                               | Serve Prometheus metrics at `/metrics`. |
| `PROMPTLAB_CORS_ORIGINS`              | empty                                | Comma-separated allowed browser origins; empty disables CORS. |
| `PROMPTLAB_RESOLVE_CACHE_TTL_SECONDS` | `2.0`                                | Per-process cache TTL for resolve lookups; `0` disables caching. |
| `PROMPTLAB_RESOLVE_CACHE_MAX_ENTRIES` | `10000`                              | Upper bound on cached resolve entries per process. |

Server options are CLI flags of `promptlab serve`: `--host` (`0.0.0.0`), `--port` (`8000`),
`--workers` (`1`) and `--forwarded-allow-ips` (`127.0.0.1`; set it to the proxy addresses, or
`*` inside a cluster, so client IPs and scheme come from `X-Forwarded-*`). The Kubernetes
Deployment passes `--workers $(WEB_CONCURRENCY)` and `--forwarded-allow-ips $(FORWARDED_ALLOW_IPS)`.

## Scaling

- **Scale horizontally.** Replicas share nothing but the database, so add pods (the HPA does
  this on CPU) rather than workers. Keep one uvicorn worker per pod: Prometheus counters are
  kept per process, so with several workers each scrape only sees one of them.
- **Size the connection pools.** Every worker process holds up to
  `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections, so

  ```text
  max_replicas x workers_per_pod x (DB_POOL_SIZE + DB_MAX_OVERFLOW)  <=  max_connections - reserve
  ```

  The production ConfigMap uses 5 + 5 per process: 20 replicas x 1 worker x 10 = 200
  connections at full scale, above PostgreSQL's default `max_connections = 100`. Either raise
  `max_connections`, lower the pool sizes or `maxReplicas`, or (recommended at scale) put
  **PgBouncer** in transaction mode between PromptLab and PostgreSQL so many client
  connections share a small server pool. Leave headroom for migrations, backups and admin
  sessions.
- **Resolve cache.** `RESOLVE_CACHE_TTL_SECONDS` (default 2 s) caches the running experiment
  (variants and versions) used by the hot `resolve` path in each process. A lifecycle change
  invalidates the entry on the replica that handled it; other replicas converge within the
  TTL. Raise it to cut database reads under heavy resolve traffic, or set `0` when changes
  must be visible everywhere immediately. Assignment itself is deterministic and never depends
  on the cache.
- **Readiness.** `/readyz` fails when the database is unreachable, so the load balancer stops
  routing to pods that cannot serve; `/healthz` does not touch the database, so a database
  outage does not trigger restart storms.

## Migrations and rollbacks

- Migrations run **before** new pods start (the `promptlab-migrate` Job in Kubernetes, the
  `migrate` service in Compose, `promptlab migrate` elsewhere). During the rolling update old
  and new pods serve traffic against the new schema at the same time, so every migration must
  be **backward compatible** with the previous release: expand first (new tables, nullable
  columns), contract (drops, renames, NOT NULL) in a later release. CI checks that migrations
  match the models and that downgrades work.
- **Roll back the application** (schema unchanged or backward compatible):

  ```bash
  kubectl -n promptlab rollout undo deployment/promptlab
  kubectl -n promptlab rollout status deployment/promptlab
  ```

  or re-deploy a previous image digest/tag through the overlay.
- **Roll back the schema** only when required, after rolling back the application and taking
  a backup: `promptlab downgrade -1` (one revision) or `promptlab downgrade <revision>`, run
  with the same image and secret as the migration Job.

## Observability

- **Metrics:** `GET /metrics` (Prometheus text format, unauthenticated; restrict it at the
  ingress if needed). Pods carry `prometheus.io/scrape`, `prometheus.io/port` and
  `prometheus.io/path` annotations; with the Prometheus Operator create a `PodMonitor`
  selecting `app.kubernetes.io/name: promptlab`. Key series:
  `promptlab_http_requests_total{method,route,status}` and
  `promptlab_http_request_duration_seconds{method,route}`. Suggested alerts: 5xx ratio above
  1% for 5 minutes, p99 latency of `resolve` above your SLO, pods not ready.
- **Logs:** one JSON object per line on stdout (`PROMPTLAB_LOG_JSON=true`) including
  `request_id`; send `X-Request-ID` from clients to correlate across services.
- **Probes:** `/healthz` (liveness, returns the version) and `/readyz` (database check).

## Backups

All state lives in PostgreSQL; the containers are disposable.

- Use your provider's automated backups with point-in-time recovery (for example RDS, Cloud
  SQL, Azure Database for PostgreSQL), or run `pg_dump --format=custom` on a schedule plus
  WAL archiving for self-managed databases.
- Take a backup (or snapshot) before every release that contains migrations.
- Regularly test restores into a scratch database and run `promptlab migrate` plus a smoke
  test against it.
- Event data (exposures, conversions) grows fastest; size storage and retention accordingly.
