"""Liveness, readiness and metrics endpoints (unauthenticated)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from promptlab import __version__
from promptlab.errors import NotFoundError
from promptlab.observability import metrics_response

router = APIRouter(tags=["operations"])
logger = logging.getLogger(__name__)


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz", summary="Readiness probe (checks the database)")
async def readyz(request: Request) -> JSONResponse:
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness check failed", exc_info=True)
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "checks": {"database": "error"}}
        )
    return JSONResponse(content={"status": "ok", "checks": {"database": "ok"}})


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    if not request.app.state.settings.metrics_enabled:
        raise NotFoundError("Metrics are disabled")
    return metrics_response()
