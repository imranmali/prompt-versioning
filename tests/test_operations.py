from __future__ import annotations

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from promptlab import __version__
from promptlab.config import Settings
from promptlab.main import create_app


async def test_healthz(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_readyz_ok(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


async def test_readyz_database_unreachable(app: FastAPI, anon_client: AsyncClient) -> None:
    healthy_engine = app.state.engine
    app.state.engine = create_async_engine("sqlite+aiosqlite:////nonexistent/dir/db.sqlite")
    try:
        response = await anon_client.get("/readyz")
    finally:
        await app.state.engine.dispose()
        app.state.engine = healthy_engine
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


async def test_metrics_exposes_request_counter(anon_client: AsyncClient) -> None:
    await anon_client.get("/healthz")
    response = await anon_client.get("/metrics")
    assert response.status_code == 200
    assert 'promptlab_http_requests_total{method="GET",route="/healthz",status="200"}' in (
        response.text
    )


async def test_metrics_can_be_disabled(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"metrics_enabled": False}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/metrics")
    await app.state.engine.dispose()
    assert response.status_code == 404


async def test_unknown_route_uses_error_envelope(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


async def test_method_not_allowed(anon_client: AsyncClient) -> None:
    response = await anon_client.post("/healthz")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_validation_error_envelope(client: AsyncClient) -> None:
    response = await client.post("/v1/api-keys", json={"role": "editor"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(d["loc"][-1] == "name" for d in error["details"])


async def test_unexpected_error_returns_internal_error(settings: Settings) -> None:
    app = create_app(settings)
    boom = APIRouter()

    @boom.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("secret internals")

    app.include_router(boom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/boom", headers={"X-Request-ID": "req-500"})
    await app.state.engine.dispose()
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret internals" not in response.text
    assert body["error"]["request_id"] == "req-500"
    assert response.headers["x-request-id"] == "req-500"


async def test_request_id_echoed(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_generated_when_missing_or_malformed(anon_client: AsyncClient) -> None:
    generated = await anon_client.get("/healthz")
    assert generated.headers["x-request-id"]
    malformed = await anon_client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert malformed.headers["x-request-id"] != "bad id with spaces"


async def test_openapi_lists_v1_routes(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/openapi.json")
    assert response.status_code == 200
    assert "/v1/api-keys" in response.json()["paths"]


async def test_cors_headers_when_configured(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"cors_origins": ["https://ui.example"]}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/healthz", headers={"Origin": "https://ui.example"})
    await app.state.engine.dispose()
    assert response.headers["access-control-allow-origin"] == "https://ui.example"
