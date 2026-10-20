from __future__ import annotations

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


async def test_create_key_returns_plaintext_once(client: AsyncClient) -> None:
    response = await client.post("/v1/api-keys", json={"name": "svc", "role": "editor"})
    assert response.status_code == 201
    body = response.json()
    assert body["key"].startswith("pl_")
    assert body["key"].startswith(body["prefix"])
    assert body["role"] == "editor"
    assert body["revoked_at"] is None


async def test_default_role_is_runtime(client: AsyncClient) -> None:
    response = await client.post("/v1/api-keys", json={"name": "svc"})
    assert response.json()["role"] == "runtime"


async def test_invalid_role_rejected(client: AsyncClient) -> None:
    response = await client.post("/v1/api-keys", json={"name": "svc", "role": "root"})
    assert response.status_code == 422


async def test_list_keys_never_exposes_secrets(client: AsyncClient) -> None:
    for i in range(3):
        await client.post("/v1/api-keys", json={"name": f"k{i}"})
    response = await client.get("/v1/api-keys", params={"limit": 2})
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert "key" not in item
        assert "key_hash" not in item
        assert set(item) == {
            "id",
            "name",
            "prefix",
            "role",
            "created_at",
            "last_used_at",
            "revoked_at",
        }


async def test_revoke_key(app: FastAPI, client: AsyncClient) -> None:
    created = (await client.post("/v1/api-keys", json={"name": "tmp", "role": "admin"})).json()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": created["key"]},
    ) as c:
        assert (await c.get("/v1/api-keys")).status_code == 200
        response = await client.delete(f"/v1/api-keys/{created['id']}")
        assert response.status_code == 204
        assert (await c.get("/v1/api-keys")).status_code == 401
    # Revoking twice is idempotent.
    assert (await client.delete(f"/v1/api-keys/{created['id']}")).status_code == 204


async def test_revoke_unknown_key(client: AsyncClient) -> None:
    response = await client.delete(f"/v1/api-keys/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
