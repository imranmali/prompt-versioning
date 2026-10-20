# PromptLab: Prompt Versioning & A/B Testing Platform

[![CI](https://github.com/imranmali/prompt-versioning/actions/workflows/ci.yml/badge.svg)](https://github.com/imranmali/prompt-versioning/actions/workflows/ci.yml)
[![CD](https://github.com/imranmali/prompt-versioning/actions/workflows/cd.yml/badge.svg)](https://github.com/imranmali/prompt-versioning/actions/workflows/cd.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)

PromptLab is a self-hosted service that treats LLM prompts like code. Every change is an
immutable, diffable **version**. You deploy a version by moving a **label** such as
`production`, and you can roll it back in one call. To find out which version actually works
better, you run **A/B experiments** on live traffic and get results with statistical tests.

```text
 your app ──resolve(prompt, user)──▶ PromptLab ──▶ version 7 (control)  or  version 9 (treatment)
 your app ──events(conversion)────▶ PromptLab ──▶ results: +4.1% lift, p = 0.003 ✔ winner
```

## Features

- **Prompt registry.** Each prompt has immutable, sequential versions that store the template,
  model settings, metadata, commit message, author and content hash. Re-submitting identical
  content is idempotent.
- **Diffs.** You get a unified diff of the template plus the variables and model settings that
  were added, removed or changed.
- **Deployment labels.** Labels like `production` and `staging` point at versions. Every label
  move is recorded with who made it and when, and a label can be rolled back in one call.
- **Safe rendering.** Templates use Jinja2 in a sandbox. Missing variables are rejected
  (`missing_variables`) and unsafe attribute access is blocked.
- **A/B experiments.** An experiment has 2–10 weighted variants, a control, a traffic
  percentage and a lifecycle of `draft → running ⇄ paused → completed`. When you complete it,
  you can promote the winner to a label.
- **Deterministic, sticky assignment.** Subjects are assigned by hashing. The same subject
  always gets the same variant on every replica, and no per-user state is stored.
- **One-call resolution.** `POST /v1/prompts/{name}/resolve` returns the version to serve (the
  subject's experiment variant, or the label as fallback), optionally renders it, and records
  the exposure.
- **Analytics.** Events are ingested in idempotent batches. Results include Wilson intervals,
  z-tests, Welch's t-test, a sample-ratio-mismatch check and winner detection.
- **Ready for production.** API keys come with `runtime`/`editor`/`admin` roles. Every error
  uses the same JSON envelope. The service provides request IDs, JSON logs, Prometheus
  metrics, health/readiness probes and Alembic migrations, and is tested on PostgreSQL and
  SQLite.
- **Delivery.** GitHub Actions runs CI and CD. The repo also includes a non-root Docker image,
  Docker Compose, and Kubernetes manifests (HPA, PDB, migration Job).

## Quick start

### Docker Compose (PostgreSQL + API)

```bash
docker compose up --build
curl http://localhost:8000/healthz
```

The compose file sets a development bootstrap admin key. See [`docker-compose.yml`](docker-compose.yml).

### Local development (uv)

```bash
uv sync                                   # install dependencies (Python 3.12+)
cp .env.example .env                      # SQLite by default
uv run promptlab migrate                  # create the schema
uv run promptlab serve --reload           # http://localhost:8000/docs
```

Interactive API docs are at `http://localhost:8000/docs` (OpenAPI at `/openapi.json`).

## Walkthrough

```bash
export PL=http://localhost:8000
export ADMIN="X-API-Key: change-me-dev-admin-key"      # PROMPTLAB_BOOTSTRAP_ADMIN_KEY

# 1. Issue scoped keys (shown once)
curl -s -X POST $PL/v1/api-keys -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"name": "ci-publisher", "role": "editor"}'
curl -s -X POST $PL/v1/api-keys -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"name": "chat-backend", "role": "runtime"}'

# 2. Create a prompt and two versions
curl -s -X POST $PL/v1/prompts -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"name": "support-reply", "description": "Customer support answer", "tags": ["support"]}'
curl -s -X POST $PL/v1/prompts/support-reply/versions -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"template": "Answer {{ customer }} politely: {{ question }}", "model_settings": {"model": "gpt-4o-mini", "temperature": 0.2}, "commit_message": "initial"}'
curl -s -X POST $PL/v1/prompts/support-reply/versions -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"template": "You are a friendly expert. Answer {{ customer }} concisely: {{ question }}", "model_settings": {"model": "gpt-4o-mini", "temperature": 0.2}, "commit_message": "friendlier tone"}'

# 3. Deploy v1 to production, compare versions
curl -s -X PUT $PL/v1/prompts/support-reply/labels/production -H "$ADMIN" -H 'content-type: application/json' -d '{"version": 1}'
curl -s "$PL/v1/prompts/support-reply/diff?from=1&to=2" -H "$ADMIN"

# 4. A/B test v1 vs v2 on 50% of traffic
EXP=$(curl -s -X POST $PL/v1/experiments -H "$ADMIN" -H 'content-type: application/json' -d '{
  "prompt": "support-reply", "name": "friendly-tone", "traffic_percent": 50,
  "variants": [{"key": "control", "version": 1, "weight": 50}, {"key": "friendly", "version": 2, "weight": 50}]
}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -X POST $PL/v1/experiments/$EXP/start -H "$ADMIN"

# 5. In your application: resolve the prompt per user (records an exposure)
curl -s -X POST $PL/v1/prompts/support-reply/resolve -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"subject_id": "user-42", "variables": {"customer": "Ada", "question": "Where is my order?"}}'

# 6. Report outcomes (batched, idempotent with event_id)
curl -s -X POST $PL/v1/events -H "$ADMIN" -H 'content-type: application/json' -d "{
  \"events\": [{\"experiment_id\": \"$EXP\", \"subject_id\": \"user-42\", \"name\": \"conversion\", \"event_id\": \"evt-1\"}]
}"

# 7. Read results, then ship the winner to production
curl -s "$PL/v1/experiments/$EXP/results?metric=conversion" -H "$ADMIN"
curl -s -X POST $PL/v1/experiments/$EXP/complete -H "$ADMIN" -H 'content-type: application/json' \
  -d '{"winner": "friendly", "promote_label": "production"}'
```

## API overview

All `/v1` endpoints need an API key, sent as `X-API-Key: <key>` or `Authorization: Bearer <key>`.

| Area | Endpoints | Minimum role |
|------|-----------|--------------|
| Operations | `GET /healthz`, `GET /readyz`, `GET /metrics` | none |
| API keys | `POST/GET /v1/api-keys`, `DELETE /v1/api-keys/{id}` | admin |
| Prompts | `POST/GET /v1/prompts`, `GET/PATCH /v1/prompts/{name}` | editor (write) / runtime (read) |
| Versions | `POST/GET /v1/prompts/{name}/versions`, `GET .../versions/{n\|latest}`, `GET .../diff?from=&to=` | editor / runtime |
| Labels | `GET .../labels`, `PUT/DELETE .../labels/{label}`, `GET .../labels/{label}/history`, `POST .../labels/{label}/rollback` | editor / runtime |
| Rendering | `POST /v1/prompts/{name}/render`, `POST /v1/prompts/{name}/resolve` | runtime |
| Experiments | `POST/GET /v1/experiments`, `GET/PATCH /v1/experiments/{id}`, `POST .../start\|pause\|complete` | editor / runtime |
| Assignment & results | `POST /v1/experiments/{id}/assign`, `GET /v1/experiments/{id}/results` | runtime |
| Events | `POST /v1/events` | runtime |

Every error uses the same envelope:

```json
{"error": {"code": "missing_variables", "message": "Missing template variables: city", "details": {"missing": ["city"]}, "request_id": "4f1c..."}}
```

Guides: [Prompts & labels](docs/prompts.md) · [Experiments & statistics](docs/experiments.md) ·
[Architecture](docs/architecture.md) · [Deployment & operations](docs/deployment.md)

## Configuration

Configuration comes from environment variables with the `PROMPTLAB_` prefix. A `.env` file is
also read.

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMPTLAB_DATABASE_URL` | `sqlite+aiosqlite:///./promptlab.db` | SQLAlchemy async URL; use `postgresql+asyncpg://…` in production |
| `PROMPTLAB_BOOTSTRAP_ADMIN_KEY` | unset | Admin key accepted without a database record (for issuing the first keys) |
| `PROMPTLAB_AUTH_ENABLED` | `true` | Disable only for local experiments |
| `PROMPTLAB_DB_POOL_SIZE` / `PROMPTLAB_DB_MAX_OVERFLOW` | `10` / `20` | Connection pool per worker process |
| `PROMPTLAB_RESOLVE_CACHE_TTL_SECONDS` | `2` | Per-replica cache for resolve (0 disables) |
| `PROMPTLAB_LOG_LEVEL` / `PROMPTLAB_LOG_JSON` | `INFO` / `true` | Logging |
| `PROMPTLAB_METRICS_ENABLED` | `true` | Expose `/metrics` |
| `PROMPTLAB_CORS_ORIGINS` | empty | Comma-separated allowed origins |

You can also create keys from the CLI:
`promptlab create-api-key --name ops --role admin`.

## Development

```bash
make install      # uv sync --frozen
make lint         # ruff check + format check
make typecheck    # mypy --strict
make test         # pytest with coverage (SQLite)
make test-postgres  # same suite on PostgreSQL (PROMPTLAB_TEST_DATABASE_URL)
make openspec     # validate OpenSpec specs and changes
```

### Spec-driven workflow

Behaviour is specified with [OpenSpec](https://github.com/Fission-AI/OpenSpec). The specs
currently in force are in [`openspec/specs/`](openspec/specs). Completed changes, each with its
proposal, design and tasks, are kept in [`openspec/changes/archive/`](openspec/changes/archive).
New work starts as a change proposal (`/opsx:propose`), is implemented against its tasks
(`/opsx:apply`), and is archived once merged (`/opsx:archive`). See
[CONTRIBUTING.md](CONTRIBUTING.md) for the branching model, commit conventions and release
process.

## Project layout

```
src/promptlab/        application package (api/, schemas/, services/, migrations/)
tests/                pytest suite (SQLite + PostgreSQL)
openspec/             specs and change history
deploy/k8s/           Kustomize manifests (base + production overlay)
docs/                 guides
.github/workflows/    CI, CD and security pipelines
```

## License

PromptLab is released under the [MIT License](LICENSE).
