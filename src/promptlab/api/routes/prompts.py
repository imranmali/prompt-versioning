"""Prompts endpoints: registry, versions, diffs, labels and rendering."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import Pagination, get_session, pagination
from promptlab.models import PromptLabel, PromptVersion
from promptlab.schemas.common import ERROR_RESPONSES, Page
from promptlab.schemas.prompts import (
    LABEL_NAME_PATTERN,
    DiffOut,
    LabelAssign,
    LabelEventOut,
    LabelOut,
    PromptCreate,
    PromptOut,
    PromptUpdate,
    RenderOut,
    RenderRequest,
    VersionCreate,
    VersionOut,
    VersionRef,
)
from promptlab.security import Principal, require_editor, require_runtime
from promptlab.services import labels as label_service
from promptlab.services import prompts as service

router = APIRouter(tags=["prompts"], responses=ERROR_RESPONSES)

LabelPath = Annotated[str, Path(pattern=LABEL_NAME_PATTERN, description="Label name")]
VersionPath = Annotated[VersionRef, Path(description="Version number or `latest`")]


def _version_out(prompt_name: str, version: PromptVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        prompt=prompt_name,
        version=version.version,
        template=version.template,
        variables=version.variables,
        model_settings=version.model_settings,
        metadata=version.metadata_,
        commit_message=version.commit_message,
        content_hash=version.content_hash,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def _label_out(record: PromptLabel) -> LabelOut:
    return LabelOut(
        name=record.name,
        version=record.version.version,
        updated_by=record.updated_by,
        updated_at=record.updated_at,
    )


# --- Prompts -------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PromptOut)
async def create_prompt(
    body: PromptCreate,
    _: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> PromptOut:
    return await service.create_prompt(session, body)


@router.get("", response_model=Page[PromptOut])
async def list_prompts(
    search: str | None = Query(None, description="Case-insensitive match on name/description"),
    tag: str | None = Query(None, description="Only prompts carrying this tag"),
    page: Pagination = Depends(pagination),
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> Page[PromptOut]:
    items, total = await service.list_prompts(session, page.limit, page.offset, search, tag)
    return Page[PromptOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{name}", response_model=PromptOut)
async def get_prompt(
    name: str,
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> PromptOut:
    return await service.describe_prompt(session, name)


@router.patch("/{name}", response_model=PromptOut)
async def update_prompt(
    name: str,
    body: PromptUpdate,
    _: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> PromptOut:
    return await service.update_prompt(session, name, body)


# --- Versions ------------------------------------------------------------------------------


@router.post(
    "/{name}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionOut,
    responses={200: {"model": VersionOut, "description": "Identical to the latest version"}},
)
async def create_version(
    name: str,
    body: VersionCreate,
    response: Response,
    principal: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> VersionOut:
    version, created = await service.create_version(session, name, body, principal.name)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _version_out(name, version)


@router.get("/{name}/versions", response_model=Page[VersionOut])
async def list_versions(
    name: str,
    page: Pagination = Depends(pagination),
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> Page[VersionOut]:
    items, total = await service.list_versions(session, name, page.limit, page.offset)
    return Page[VersionOut](
        items=[_version_out(name, v) for v in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{name}/versions/{version}", response_model=VersionOut)
async def get_version(
    name: str,
    version: VersionPath,
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> VersionOut:
    return _version_out(name, await service.fetch_version(session, name, version))


@router.get("/{name}/diff", response_model=DiffOut)
async def diff_versions(
    name: str,
    from_: VersionRef = Query(alias="from", description="Base version number or `latest`"),
    to: VersionRef = Query(description="Target version number or `latest`"),
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> DiffOut:
    return await service.diff(session, name, from_, to)


# --- Labels --------------------------------------------------------------------------------


@router.get("/{name}/labels", response_model=list[LabelOut])
async def list_labels(
    name: str,
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> list[LabelOut]:
    return [_label_out(r) for r in await label_service.list_labels(session, name)]


@router.put("/{name}/labels/{label}", response_model=LabelOut)
async def set_label(
    name: str,
    label: LabelPath,
    body: LabelAssign,
    principal: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> LabelOut:
    record = await label_service.set_label(session, name, label, body.version, principal.name)
    return _label_out(record)


@router.delete("/{name}/labels/{label}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    name: str,
    label: LabelPath,
    principal: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await label_service.delete_label(session, name, label, principal.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/labels/{label}/history", response_model=Page[LabelEventOut])
async def label_history(
    name: str,
    label: LabelPath,
    page: Pagination = Depends(pagination),
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> Page[LabelEventOut]:
    events, total = await label_service.label_history(session, name, label, page.limit, page.offset)
    return Page[LabelEventOut](
        items=[LabelEventOut.model_validate(e) for e in events],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/{name}/labels/{label}/rollback", response_model=LabelOut)
async def rollback_label(
    name: str,
    label: LabelPath,
    principal: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
) -> LabelOut:
    return _label_out(await label_service.rollback_label(session, name, label, principal.name))


# --- Rendering -----------------------------------------------------------------------------


@router.post("/{name}/render", response_model=RenderOut)
async def render_prompt(
    name: str,
    body: RenderRequest,
    _: Principal = Depends(require_runtime),
    session: AsyncSession = Depends(get_session),
) -> RenderOut:
    version, rendered = await service.render(
        session, name, body.variables, version=body.version, label=body.label
    )
    return RenderOut(
        prompt=name,
        version=version.version,
        label=body.label,
        rendered=rendered,
        model_settings=version.model_settings,
    )
