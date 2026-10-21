"""Experiments endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import Pagination, get_resolve_cache, get_session, pagination
from promptlab.cache import TTLCache
from promptlab.models import ExperimentStatus
from promptlab.schemas.common import ERROR_RESPONSES, Page
from promptlab.schemas.experiments import (
    METRIC_PATTERN,
    AssignRequest,
    AssignResponse,
    ExperimentComplete,
    ExperimentCreate,
    ExperimentOut,
    ExperimentResults,
    ExperimentUpdate,
    MetricKind,
)
from promptlab.security import Principal, require_editor, require_runtime
from promptlab.services import analytics
from promptlab.services import experiments as service

router = APIRouter(tags=["experiments"], responses=ERROR_RESPONSES)

Cache = TTLCache[str, object]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperimentOut,
    dependencies=[Depends(require_editor)],
)
async def create_experiment(
    body: ExperimentCreate, session: AsyncSession = Depends(get_session)
) -> ExperimentOut:
    return service.to_out(await service.create_experiment(session, body))


@router.get("", response_model=Page[ExperimentOut], dependencies=[Depends(require_runtime)])
async def list_experiments(
    prompt: str | None = Query(None, description="Only experiments of this prompt"),
    status: ExperimentStatus | None = Query(None, description="Only experiments in this status"),
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[ExperimentOut]:
    items, total = await service.list_experiments(
        session, prompt=prompt, status=status, limit=page.limit, offset=page.offset
    )
    return Page[ExperimentOut](
        items=[service.to_out(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{experiment_id}", response_model=ExperimentOut, dependencies=[Depends(require_runtime)]
)
async def get_experiment(
    experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ExperimentOut:
    return service.to_out(await service.get_experiment(session, experiment_id))


@router.patch(
    "/{experiment_id}", response_model=ExperimentOut, dependencies=[Depends(require_editor)]
)
async def update_experiment(
    experiment_id: uuid.UUID,
    body: ExperimentUpdate,
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_resolve_cache),
) -> ExperimentOut:
    return service.to_out(await service.update_experiment(session, cache, experiment_id, body))


@router.post(
    "/{experiment_id}/start", response_model=ExperimentOut, dependencies=[Depends(require_editor)]
)
async def start_experiment(
    experiment_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_resolve_cache),
) -> ExperimentOut:
    return service.to_out(await service.start_experiment(session, cache, experiment_id))


@router.post(
    "/{experiment_id}/pause", response_model=ExperimentOut, dependencies=[Depends(require_editor)]
)
async def pause_experiment(
    experiment_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_resolve_cache),
) -> ExperimentOut:
    return service.to_out(await service.pause_experiment(session, cache, experiment_id))


@router.post("/{experiment_id}/complete", response_model=ExperimentOut)
async def complete_experiment(
    experiment_id: uuid.UUID,
    body: ExperimentComplete | None = None,
    principal: Principal = Depends(require_editor),
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_resolve_cache),
) -> ExperimentOut:
    experiment = await service.complete_experiment(
        session, cache, experiment_id, body or ExperimentComplete(), principal.name
    )
    return service.to_out(experiment)


@router.post(
    "/{experiment_id}/assign",
    response_model=AssignResponse,
    dependencies=[Depends(require_runtime)],
)
async def assign_subject(
    experiment_id: uuid.UUID, body: AssignRequest, session: AsyncSession = Depends(get_session)
) -> AssignResponse:
    return await service.assign_subject(session, experiment_id, body.subject_id)


@router.get(
    "/{experiment_id}/results",
    response_model=ExperimentResults,
    dependencies=[Depends(require_runtime)],
)
async def experiment_results(
    experiment_id: uuid.UUID,
    metric: str | None = Query(
        None, pattern=METRIC_PATTERN, description="Defaults to the experiment's primary metric"
    ),
    kind: MetricKind = Query("binary", description="`binary` (conversion) or `numeric` (mean)"),
    alpha: float = Query(0.05, gt=0, lt=0.5, description="Significance level"),
    session: AsyncSession = Depends(get_session),
) -> ExperimentResults:
    return await analytics.experiment_results(
        session, experiment_id, metric=metric, kind=kind, alpha=alpha
    )
