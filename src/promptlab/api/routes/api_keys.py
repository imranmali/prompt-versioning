"""Admin endpoints for issuing and revoking API keys."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import Pagination, get_session, pagination
from promptlab.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from promptlab.schemas.common import ERROR_RESPONSES, Page
from promptlab.security import require_admin
from promptlab.services import api_keys as service

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_admin)],
    responses=ERROR_RESPONSES,
)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreated)
async def create_api_key(
    body: ApiKeyCreate, session: AsyncSession = Depends(get_session)
) -> ApiKeyCreated:
    record, plaintext = await service.create_api_key(session, body.name, body.role)
    return ApiKeyCreated.model_validate(
        {**ApiKeyOut.model_validate(record).model_dump(), "key": plaintext}
    )


@router.get("", response_model=Page[ApiKeyOut])
async def list_api_keys(
    page: Pagination = Depends(pagination), session: AsyncSession = Depends(get_session)
) -> Page[ApiKeyOut]:
    items, total = await service.list_api_keys(session, page.limit, page.offset)
    return Page[ApiKeyOut](
        items=[ApiKeyOut.model_validate(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    await service.revoke_api_key(session, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
