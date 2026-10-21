"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from promptlab import __version__
from promptlab.api.routes import api_keys, events, experiments, health, prompts, resolve
from promptlab.cache import TTLCache
from promptlab.config import Settings, get_settings
from promptlab.db import create_engine, create_session_factory
from promptlab.errors import register_error_handlers
from promptlab.observability import RequestContextMiddleware, configure_logging

API_DESCRIPTION = """
PromptLab stores every prompt change as an immutable version, deploys versions through
movable labels (`production`, `staging`, ...) and runs A/B experiments between versions with
deterministic assignment and built-in statistical analysis.

Authenticate with an API key in the `X-API-Key` header or as `Authorization: Bearer <key>`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(
        title="PromptLab",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.resolve_cache = TTLCache[str, object](
        settings.resolve_cache_ttl_seconds, settings.resolve_cache_max_entries
    )

    register_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestContextMiddleware, metrics_enabled=settings.metrics_enabled)

    v1 = APIRouter(prefix="/v1")
    v1.include_router(api_keys.router)
    v1.include_router(prompts.router, prefix="/prompts")
    v1.include_router(resolve.router, prefix="/prompts")
    v1.include_router(experiments.router, prefix="/experiments")
    v1.include_router(events.router, prefix="/events")
    app.include_router(health.router)
    app.include_router(v1)
    return app


def build_app() -> FastAPI:
    """Entry point for ASGI servers (``uvicorn --factory promptlab.main:build_app``)."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    return create_app(settings)
