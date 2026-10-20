# syntax=docker/dockerfile:1.7
#
# PromptLab container image.
#
#   docker build -t promptlab .
#   docker run --rm -p 8000:8000 -e PROMPTLAB_DATABASE_URL=... promptlab
#
# The builder stage resolves dependencies from uv.lock into /app/.venv; the runtime
# stage copies only that virtual environment and runs as an unprivileged user.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.32

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
# Builder: install locked dependencies and the project (non-editable) into /app/.venv
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first: this layer is reused until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

# Then the project itself (hatchling needs README.md and LICENSE for the metadata).
COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Runtime: slim base + virtual environment only, non-root
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="PromptLab" \
      org.opencontainers.image.description="Prompt versioning and A/B testing platform for LLM applications" \
      org.opencontainers.image.source="https://github.com/imranmali/prompt-versioning" \
      org.opencontainers.image.url="https://github.com/imranmali/prompt-versioning" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system --gid 10001 promptlab \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home \
       --shell /usr/sbin/nologin promptlab

WORKDIR /app

# The venv stays root-owned (read-only for the service user).
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10001:10001

EXPOSE 8000

# Liveness only (no database round-trip); slim images ship without curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# Every CLI sub-command is available: `serve` (default), `migrate`, `downgrade`, `create-api-key`.
# Uvicorn worker processes: append `--workers N` (Kubernetes passes `--workers $(WEB_CONCURRENCY)`).
ENTRYPOINT ["promptlab"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
