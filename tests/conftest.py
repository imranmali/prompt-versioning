"""Shared fixtures.

Tests run against SQLite by default. Set ``PROMPTLAB_TEST_DATABASE_URL`` (e.g. to a
``postgresql+asyncpg://`` URL) to run the same suite against PostgreSQL.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.config import Settings
from promptlab.db import Base
from promptlab.main import create_app

ADMIN_KEY = "test-bootstrap-admin-key"

ClientFactory = Callable[[str], Awaitable[AsyncClient]]


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return os.environ.get(
        "PROMPTLAB_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'promptlab.db'}"
    )


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        bootstrap_admin_key=ADMIN_KEY,
        log_json=False,
        resolve_cache_ttl_seconds=0,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    engine = application.state.engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield application
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _client(app: FastAPI, key: str | None) -> AsyncClient:
    headers = {"X-API-Key": key} if key else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client authenticated with the bootstrap admin key."""
    async with _client(app, ADMIN_KEY) as c:
        yield c


@pytest.fixture
async def anon_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _client(app, None) as c:
        yield c


@pytest.fixture
async def client_for_role(app: FastAPI, client: AsyncClient) -> AsyncIterator[ClientFactory]:
    """Factory returning a client authenticated with a freshly issued key of ``role``."""
    opened: list[AsyncClient] = []

    async def factory(role: str) -> AsyncClient:
        response = await client.post("/v1/api-keys", json={"name": f"{role}-key", "role": role})
        assert response.status_code == 201, response.text
        c = _client(app, response.json()["key"])
        opened.append(c)
        return c

    yield factory
    for c in opened:
        await c.aclose()


@pytest.fixture
async def editor_client(client_for_role: ClientFactory) -> AsyncClient:
    return await client_for_role("editor")


@pytest.fixture
async def runtime_client(client_for_role: ClientFactory) -> AsyncClient:
    return await client_for_role("runtime")


@pytest.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.session_factory() as s:
        yield s
