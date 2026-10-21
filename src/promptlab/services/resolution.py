"""Experiment-aware resolution of the prompt version to serve for a subject.

The hot path loads an immutable snapshot of the prompt's running experiment through the bounded
TTL cache and computes the assignment in memory. Lifecycle changes invalidate the local entry
(:func:`invalidate_prompt`); other replicas converge within the TTL.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from promptlab.cache import TTLCache
from promptlab.models import EXPOSURE_EVENT, Event, Experiment, ExperimentStatus
from promptlab.schemas.resolve import ResolvedExperiment, ResolveRequest, ResolveResponse
from promptlab.services import assignment
from promptlab.services.labels import get_label_version
from promptlab.services.lookups import get_prompt
from promptlab.services.templating import render


@dataclass(frozen=True, slots=True)
class VariantSnapshot:
    id: uuid.UUID
    key: str
    weight: int
    version: int
    template: str
    model_settings: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ExperimentSnapshot:
    id: uuid.UUID
    name: str
    salt: str
    traffic_percent: int
    status: ExperimentStatus
    fallback_label: str
    variants: tuple[VariantSnapshot, ...]

    @property
    def weights(self) -> tuple[int, ...]:
        return tuple(v.weight for v in self.variants)

    def assign(self, subject_id: str) -> VariantSnapshot | None:
        if self.status != ExperimentStatus.RUNNING:
            return None
        index = assignment.assign(self.salt, self.traffic_percent, self.weights, subject_id)
        return self.variants[index] if index is not None else None


@dataclass(frozen=True, slots=True)
class PromptSnapshot:
    """Cached per prompt name; ``experiment`` is ``None`` when none is running."""

    prompt_id: uuid.UUID
    name: str
    experiment: ExperimentSnapshot | None


def invalidate_prompt(cache: TTLCache[str, object], prompt_name: str) -> None:
    """Drop the cached snapshot of ``prompt_name`` (call after any experiment change)."""
    cache.invalidate(prompt_name)


async def load_snapshot(session: AsyncSession, name: str) -> PromptSnapshot:
    """Load the prompt and its running experiment (raises ``NotFoundError`` for unknown prompts)."""
    prompt = await get_prompt(session, name)
    experiment = await session.scalar(
        select(Experiment)
        .options(selectinload(Experiment.variants))
        .where(Experiment.prompt_id == prompt.id, Experiment.status == ExperimentStatus.RUNNING)
        .order_by(Experiment.started_at.desc())
        .limit(1)
    )
    experiment_snapshot = None
    if experiment is not None:
        experiment_snapshot = ExperimentSnapshot(
            id=experiment.id,
            name=experiment.name,
            salt=experiment.salt,
            traffic_percent=experiment.traffic_percent,
            status=experiment.status,
            fallback_label=experiment.fallback_label,
            variants=tuple(
                VariantSnapshot(
                    id=v.id,
                    key=v.key,
                    weight=v.weight,
                    version=v.version.version,
                    template=v.version.template,
                    model_settings=MappingProxyType(copy.deepcopy(v.version.model_settings)),
                )
                for v in experiment.variants
            ),
        )
    return PromptSnapshot(prompt_id=prompt.id, name=prompt.name, experiment=experiment_snapshot)


async def get_snapshot(
    session: AsyncSession, cache: TTLCache[str, object], name: str
) -> PromptSnapshot:
    cached = cache.get(name)
    if isinstance(cached, PromptSnapshot):
        return cached
    snapshot = await load_snapshot(session, name)
    cache.set(name, snapshot)
    return snapshot


def _render(template: str, variables: Mapping[str, Any] | None) -> str | None:
    return render(template, variables) if variables is not None else None


async def resolve_prompt(
    session: AsyncSession, cache: TTLCache[str, object], name: str, request: ResolveRequest
) -> ResolveResponse:
    snapshot = await get_snapshot(session, cache, name)
    experiment = snapshot.experiment
    if request.subject_id is not None and experiment is not None:
        variant = experiment.assign(request.subject_id)
        if variant is not None:
            rendered = _render(variant.template, request.variables)
            if request.record_exposure:
                session.add(
                    Event(
                        experiment_id=experiment.id,
                        variant_id=variant.id,
                        subject_id=request.subject_id,
                        name=EXPOSURE_EVENT,
                        value=1.0,
                    )
                )
                await session.commit()
            return ResolveResponse(
                prompt=snapshot.name,
                version=variant.version,
                label=None,
                template=variant.template,
                model_settings=copy.deepcopy(dict(variant.model_settings)),
                rendered=rendered,
                experiment=ResolvedExperiment(
                    id=experiment.id, name=experiment.name, variant=variant.key
                ),
            )

    # Traffic outside a running experiment is served the experiment's fallback label unless the
    # caller explicitly asked for a label.
    label = request.label
    if experiment is not None and "label" not in request.model_fields_set:
        label = experiment.fallback_label
    prompt = await get_prompt(session, name)
    version = await get_label_version(session, prompt, label)
    return ResolveResponse(
        prompt=prompt.name,
        version=version.version,
        label=label,
        template=version.template,
        model_settings=version.model_settings,
        rendered=_render(version.template, request.variables),
        experiment=None,
    )
