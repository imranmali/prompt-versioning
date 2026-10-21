"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.cache import TTLCache
from promptlab.config import Settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session; services commit explicitly, anything else is rolled back."""
    async with request.app.state.session_factory() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_resolve_cache(request: Request) -> TTLCache[str, object]:
    cache: TTLCache[str, object] = request.app.state.resolve_cache
    return cache


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
