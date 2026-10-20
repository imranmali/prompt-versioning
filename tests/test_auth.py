from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from promptlab.config import Settings
from promptlab.main import create_app
from tests.conftest import ClientFactory


async def test_missing_key_is_unauthorized(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/v1/api-keys")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_key_is_unauthorized(app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "pl_wrong"},
    ) as c:
        response = await c.get("/v1/api-keys")
    assert response.status_code == 401


async def test_bearer_token_accepted(app: FastAPI, client: AsyncClient) -> None:
    created = await client.post("/v1/api-keys", json={"name": "ci", "role": "admin"})
    key = created.json()["key"]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {key}"},
    ) as c:
        response = await c.get("/v1/api-keys")
    assert response.status_code == 200


async def test_role_hierarchy(client_for_role: ClientFactory) -> None:
    runtime = await client_for_role("runtime")
    editor = await client_for_role("editor")
    admin = await client_for_role("admin")
    assert (await runtime.get("/v1/api-keys")).status_code == 403
    forbidden = await editor.get("/v1/api-keys")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    assert forbidden.json()["error"]["details"] == {"required_role": "admin", "role": "editor"}
    assert (await admin.get("/v1/api-keys")).status_code == 200


async def test_last_used_at_recorded(client: AsyncClient, client_for_role: ClientFactory) -> None:
    admin = await client_for_role("admin")
    await admin.get("/v1/api-keys")
    listing = (await client.get("/v1/api-keys")).json()["items"]
    assert listing[0]["last_used_at"] is not None


async def test_auth_disabled_allows_anonymous_admin(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"auth_enabled": False}))
    from promptlab.db import Base

    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/v1/api-keys")
    await app.state.engine.dispose()
    assert response.status_code == 200


async def test_bootstrap_key_absent_when_unset(app: FastAPI, settings: Settings) -> None:
    # ``app`` fixture creates the schema in the shared test database.
    no_bootstrap = create_app(settings.model_copy(update={"bootstrap_admin_key": None}))
    async with AsyncClient(
        transport=ASGITransport(app=no_bootstrap),
        base_url="http://test",
        headers={"X-API-Key": "test-bootstrap-admin-key"},
    ) as c:
        response = await c.get("/v1/api-keys")
    await no_bootstrap.state.engine.dispose()
    assert response.status_code == 401
