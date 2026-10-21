"""Resolve endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import get_resolve_cache, get_session
from promptlab.cache import TTLCache
from promptlab.schemas.common import ERROR_RESPONSES
from promptlab.schemas.resolve import ResolveRequest, ResolveResponse
from promptlab.security import require_runtime
from promptlab.services import resolution

router = APIRouter(tags=["prompts"], responses=ERROR_RESPONSES)


@router.post(
    "/{name}/resolve", response_model=ResolveResponse, dependencies=[Depends(require_runtime)]
)
async def resolve_prompt(
    name: str,
    body: ResolveRequest,
    session: AsyncSession = Depends(get_session),
    cache: TTLCache[str, object] = Depends(get_resolve_cache),
) -> ResolveResponse:
    """Return the version to serve: the subject's experiment variant or the label's version."""
    return await resolution.resolve_prompt(session, cache, name, body)
