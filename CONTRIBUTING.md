# Contributing to PromptLab

Thanks for helping improve PromptLab. This guide covers the local setup, the workflow every
change follows and how releases are cut. By participating you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## Development setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22 (OpenSpec CLI) and,
optionally, Docker for PostgreSQL and image builds.

```bash
git clone https://github.com/imranmali/prompt-versioning.git
cd prompt-versioning
uv sync --frozen            # creates .venv with runtime + dev dependencies from uv.lock
cp .env.example .env        # local settings (SQLite by default)
uv run promptlab migrate    # create the schema
make run                    # http://localhost:8000/docs (auto-reload)
```

Add or upgrade dependencies with `uv add <pkg>` / `uv lock --upgrade-package <pkg>` and commit
both `pyproject.toml` and `uv.lock`. CI installs with `--frozen` and fails on a stale lock.

### Make targets

| Target               | What it does                                                    |
| -------------------- | --------------------------------------------------------------- |
| `make install`       | `uv sync --frozen`                                              |
| `make lint`          | `ruff check` and `ruff format --check`                          |
| `make format`        | Apply ruff fixes and formatting                                 |
| `make typecheck`     | `mypy` (strict)                                                 |
| `make test`          | pytest with coverage on SQLite (fails under 90%)                |
| `make test-postgres` | The same suite against PostgreSQL (`PROMPTLAB_TEST_DATABASE_URL`) |
| `make openspec`      | `openspec validate --all --strict`                              |
| `make check`         | lint + typecheck + test + openspec (run before pushing)         |
| `make run`           | Development server with auto-reload                             |
| `make migrate`       | Apply migrations to `PROMPTLAB_DATABASE_URL`                    |
| `make docker-build`  | Build the container image (`IMAGE=promptlab:local`)             |
| `make compose-up`    | Start PostgreSQL, run migrations and start the API with Compose |
| `make compose-down`  | Stop the Compose stack (`docker compose down -v` drops data)    |
| `make compose-logs`  | Follow the API logs                                             |

### Testing on PostgreSQL

Tests use SQLite by default. Production runs PostgreSQL, so run the suite against it whenever
you touch queries, models or migrations:

```bash
docker run -d --name promptlab-pg -p 5432:5432 \
  -e POSTGRES_USER=promptlab -e POSTGRES_PASSWORD=promptlab -e POSTGRES_DB=promptlab_test \
  postgres:16
make test-postgres
# or: PROMPTLAB_TEST_DATABASE_URL=postgresql+asyncpg://promptlab:promptlab@localhost:5432/promptlab_test uv run pytest
```

## Branching model

- `main` is protected. It is only updated through pull requests whose required
  **`ci-success`** check is green (it aggregates every CI job). No direct pushes.
- Work happens on short-lived topic branches named by intent:
  `feature/<topic>`, `fix/<topic>`, `ci/<topic>`, `docs/<topic>`.
- A topic branch is either opened as a pull request against `main` directly, or merged with
  `git merge --no-ff` into an integration branch that is then pull-requested, so each topic
  remains visible as a merge in history.
- Keep branches rebased on (or merged with) the latest `main` before requesting review.

## Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```text
<type>(<optional scope>): <imperative summary>

<body: what and why>
```

Types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.
Mark breaking changes with `!` (`feat(api)!: ...`) and a `BREAKING CHANGE:` footer. Examples:
`feat(experiments): add sample-ratio-mismatch check`, `fix(labels): reject moves to archived
versions`, `build(deps): bump fastapi`.

## Spec-driven changes with OpenSpec

Behavioural changes are specified before they are built, using [OpenSpec](https://github.com/Fission-AI/OpenSpec)
(`openspec/`). Small fixes, docs and dependency bumps do not need a change.

1. **Propose**: create `openspec/changes/<change-id>/` with `proposal.md` (why, what changes,
   out of scope), `design.md` when there are decisions to record, `tasks.md` and delta specs
   under `specs/<capability>/spec.md`.
2. **Apply**: implement the tasks on a topic branch, ticking each `- [x]` in `tasks.md` once it is
   done and verified. Each task group lands with its tests and docs.
3. **Archive**: after the pull request is merged, archive the change so its deltas are folded
   into `openspec/specs/` (`openspec archive <change-id>`).

Validate everything before pushing (CI runs the same command):

```bash
npx --yes @fission-ai/openspec@1.14.3 validate --all --strict   # or: make openspec
```

## Pull requests

- Fill in the [pull request template](.github/pull_request_template.md): summary, OpenSpec
  change, type of change, testing evidence and checklist.
- CI (`.github/workflows/ci.yml`) must pass: lint and types, tests on Python 3.12 and 3.13
  (SQLite), tests on PostgreSQL, migration upgrade/`alembic check`/downgrade/upgrade, OpenSpec
  validation and a Docker build with a container smoke test.
- The dependency audit (`.github/workflows/security.yml`, `pip-audit`) runs on pull requests,
  on `main` and weekly, but is **deliberately not part of `ci-success`**: a newly published
  advisory for an existing dependency should not block unrelated pull requests. When it fails,
  bump the affected dependency in a dedicated `build(deps)` pull request (Dependabot usually
  opens one).

## Database migrations

- Generate migrations with Alembic and review them by hand:
  `uv run alembic revision --autogenerate -m "add foo"`. CI fails if models and migrations
  drift (`alembic check`) or if a downgrade does not work.
- **Migrations must be backward compatible with the release that is currently running.** In
  production the migration Job runs to completion *before* the new pods roll out, and old pods
  keep serving traffic against the migrated schema during the rolling update. Use the
  expand/contract pattern: add nullable columns or new tables first, deploy code that uses
  them, and only drop or rename columns in a later release once nothing reads them.

## Release process

1. Make sure `main` is green.
2. On a `chore/release-X.Y.Z` branch, bump `version` in `pyproject.toml`, run `uv lock`, and
   move the `[Unreleased]` entries in `CHANGELOG.md` to a new `## [X.Y.Z] - YYYY-MM-DD`
   section (update the compare links). Merge it through a pull request.
3. Tag the merge commit and push the tag:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "PromptLab vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. The CD workflow (`.github/workflows/cd.yml`) publishes
   `ghcr.io/imranmali/prompt-versioning:X.Y.Z` and `:X.Y` (multi-arch), creates the GitHub
   Release with generated notes and, if deployment is enabled, rolls it out to production.
   See [docs/deployment.md](docs/deployment.md).
