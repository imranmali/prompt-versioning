"""Experiment definition, validation and lifecycle."""

from __future__ import annotations

import secrets
import uuid
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from promptlab.cache import TTLCache
from promptlab.db import utcnow
from promptlab.errors import ConflictError, InvalidStateError, NotFoundError, UnprocessableError
from promptlab.models import Experiment, ExperimentStatus, ExperimentVariant, Prompt, PromptVersion
from promptlab.schemas.experiments import (
    AssignedVariant,
    AssignResponse,
    ExperimentComplete,
    ExperimentCreate,
    ExperimentOut,
    ExperimentUpdate,
    VariantIn,
    VariantOut,
)
from promptlab.services import assignment
from promptlab.services.labels import move_label
from promptlab.services.lookups import get_prompt
from promptlab.services.resolution import invalidate_prompt

_EXPERIMENT_LOADERS = (
    selectinload(Experiment.prompt),
    selectinload(Experiment.variants),
)


def _experiment_query() -> Select[Experiment]:
    return select(Experiment).options(*_EXPERIMENT_LOADERS)


def to_out(experiment: Experiment) -> ExperimentOut:
    """Serialize an experiment loaded with its prompt and variants."""
    winner = next(
        (v.key for v in experiment.variants if v.id == experiment.winner_variant_id), None
    )
    return ExperimentOut(
        id=experiment.id,
        prompt=experiment.prompt.name,
        name=experiment.name,
        description=experiment.description,
        status=experiment.status,
        traffic_percent=experiment.traffic_percent,
        primary_metric=experiment.primary_metric,
        fallback_label=experiment.fallback_label,
        salt=experiment.salt,
        variants=[
            VariantOut(
                id=v.id,
                key=v.key,
                version=v.version.version,
                weight=v.weight,
                is_control=v.is_control,
            )
            for v in experiment.variants
        ],
        winner=winner,
        started_at=experiment.started_at,
        ended_at=experiment.ended_at,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )


async def get_experiment(session: AsyncSession, experiment_id: uuid.UUID) -> Experiment:
    """Return the experiment with its prompt and variants loaded, or raise ``NotFoundError``."""
    experiment = await session.scalar(
        _experiment_query()
        .where(Experiment.id == experiment_id)
        .execution_options(populate_existing=True)
    )
    if experiment is None:
        raise NotFoundError(f"Experiment '{experiment_id}' not found")
    return experiment


async def _build_variants(
    session: AsyncSession, prompt: Prompt, variants: Sequence[VariantIn]
) -> list[ExperimentVariant]:
    """Validate variant definitions and return unsaved variant rows (positions = list order)."""
    duplicated = sorted(key for key, n in Counter(v.key for v in variants).items() if n > 1)
    if duplicated:
        raise UnprocessableError(
            "Variant keys must be unique", details={"duplicate_keys": duplicated}
        )
    controls = [v.key for v in variants if v.is_control]
    if len(controls) > 1:
        raise UnprocessableError(
            "Only one variant can be the control", details={"controls": controls}
        )

    numbers = {v.version for v in variants}
    rows = await session.scalars(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt.id, PromptVersion.version.in_(numbers)
        )
    )
    versions = {row.version: row for row in rows}
    missing = sorted(numbers - versions.keys())
    if missing:
        raise UnprocessableError(
            f"Prompt '{prompt.name}' has no version(s) {', '.join(map(str, missing))}",
            details={"unknown_versions": missing},
        )

    control_index = next((i for i, v in enumerate(variants) if v.is_control), 0)
    return [
        ExperimentVariant(
            key=v.key,
            version=versions[v.version],
            weight=v.weight,
            is_control=i == control_index,
            position=i,
        )
        for i, v in enumerate(variants)
    ]


async def create_experiment(session: AsyncSession, data: ExperimentCreate) -> Experiment:
    prompt = await get_prompt(session, data.prompt)
    prompt_name = prompt.name
    variants = await _build_variants(session, prompt, data.variants)
    experiment_id = uuid.uuid4()
    experiment = Experiment(
        id=experiment_id,
        prompt=prompt,
        name=data.name,
        description=data.description,
        status=ExperimentStatus.DRAFT,
        salt=data.salt or secrets.token_hex(8),
        traffic_percent=data.traffic_percent,
        primary_metric=data.primary_metric,
        fallback_label=data.fallback_label,
        variants=variants,
    )
    session.add(experiment)
    try:
        await session.commit()
    except IntegrityError as exc:  # the unique (prompt_id, name) constraint
        await session.rollback()
        raise ConflictError(
            f"Experiment '{data.name}' already exists for prompt '{prompt_name}'"
        ) from exc
    return await get_experiment(session, experiment_id)


async def list_experiments(
    session: AsyncSession,
    *,
    prompt: str | None,
    status: ExperimentStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Experiment], int]:
    conditions = []
    if prompt is not None:
        conditions.append(Experiment.prompt.has(Prompt.name == prompt))
    if status is not None:
        conditions.append(Experiment.status == status)
    total = await session.scalar(select(func.count(Experiment.id)).where(*conditions)) or 0
    rows = await session.scalars(
        _experiment_query()
        .where(*conditions)
        .order_by(Experiment.created_at.desc(), Experiment.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


async def update_experiment(
    session: AsyncSession,
    cache: TTLCache[str, object],
    experiment_id: uuid.UUID,
    data: ExperimentUpdate,
) -> Experiment:
    """Apply a partial update: only the description may change outside ``draft``."""
    experiment = await get_experiment(session, experiment_id)
    changes = data.model_dump(exclude_none=True, exclude={"variants"})
    if data.variants is not None:
        changes["variants"] = data.variants
    if experiment.status == ExperimentStatus.COMPLETED:
        raise InvalidStateError("Completed experiments cannot be modified")
    restricted = sorted(set(changes) - {"description"})
    if restricted and experiment.status != ExperimentStatus.DRAFT:
        raise InvalidStateError(
            f"Only the description can be changed while the experiment is "
            f"{experiment.status.value}",
            details={"fields": restricted, "status": experiment.status.value},
        )

    if data.variants is not None:
        variants = await _build_variants(session, experiment.prompt, data.variants)
        # Delete the old rows first so re-used keys do not trip the unique constraint.
        experiment.variants.clear()
        await session.flush()
        experiment.variants.extend(variants)
    for field in ("description", "traffic_percent", "primary_metric", "fallback_label"):
        if field in changes:
            setattr(experiment, field, changes[field])
    experiment.updated_at = utcnow()
    await session.commit()
    invalidate_prompt(cache, experiment.prompt.name)
    return await get_experiment(session, experiment.id)


def _require_status(experiment: Experiment, action: str, *allowed: ExperimentStatus) -> None:
    if experiment.status not in allowed:
        raise InvalidStateError(
            f"Cannot {action} an experiment that is {experiment.status.value}",
            details={
                "status": experiment.status.value,
                "allowed": [status.value for status in allowed],
            },
        )


async def start_experiment(
    session: AsyncSession, cache: TTLCache[str, object], experiment_id: uuid.UUID
) -> Experiment:
    experiment = await get_experiment(session, experiment_id)
    _require_status(experiment, "start", ExperimentStatus.DRAFT, ExperimentStatus.PAUSED)
    # Serialize concurrent starts on the same prompt (row lock; a no-op on SQLite).
    await session.execute(
        select(Prompt.id).where(Prompt.id == experiment.prompt_id).with_for_update()
    )
    running = await session.scalar(
        select(Experiment.name).where(
            Experiment.prompt_id == experiment.prompt_id,
            Experiment.status == ExperimentStatus.RUNNING,
            Experiment.id != experiment.id,
        )
    )
    if running is not None:
        raise ConflictError(
            f"Experiment '{running}' is already running on prompt '{experiment.prompt.name}'",
            details={"running_experiment": running},
        )
    now = utcnow()
    experiment.status = ExperimentStatus.RUNNING
    if experiment.started_at is None:
        experiment.started_at = now
    experiment.updated_at = now
    await session.commit()
    invalidate_prompt(cache, experiment.prompt.name)
    return await get_experiment(session, experiment.id)


async def pause_experiment(
    session: AsyncSession, cache: TTLCache[str, object], experiment_id: uuid.UUID
) -> Experiment:
    experiment = await get_experiment(session, experiment_id)
    _require_status(experiment, "pause", ExperimentStatus.RUNNING)
    experiment.status = ExperimentStatus.PAUSED
    experiment.updated_at = utcnow()
    await session.commit()
    invalidate_prompt(cache, experiment.prompt.name)
    return await get_experiment(session, experiment.id)


async def complete_experiment(
    session: AsyncSession,
    cache: TTLCache[str, object],
    experiment_id: uuid.UUID,
    data: ExperimentComplete,
    actor: str,
) -> Experiment:
    """Complete the experiment, optionally recording a winner and promoting it to a label.

    The status change and the label move are committed in one transaction.
    """
    if data.promote_label is not None and data.winner is None:
        raise UnprocessableError("'promote_label' requires 'winner'")
    experiment = await get_experiment(session, experiment_id)
    _require_status(experiment, "complete", ExperimentStatus.RUNNING, ExperimentStatus.PAUSED)

    winner: ExperimentVariant | None = None
    if data.winner is not None:
        winner = next((v for v in experiment.variants if v.key == data.winner), None)
        if winner is None:
            raise UnprocessableError(
                f"Experiment has no variant '{data.winner}'",
                details={"variants": [v.key for v in experiment.variants]},
            )

    now = utcnow()
    experiment.status = ExperimentStatus.COMPLETED
    experiment.ended_at = now
    experiment.updated_at = now
    experiment.winner_variant_id = winner.id if winner is not None else None
    if winner is not None and data.promote_label is not None:
        await move_label(session, experiment.prompt, data.promote_label, winner.version, actor)
    await session.commit()
    invalidate_prompt(cache, experiment.prompt.name)
    return await get_experiment(session, experiment.id)


async def assign_subject(
    session: AsyncSession, experiment_id: uuid.UUID, subject_id: str
) -> AssignResponse:
    """Deterministic assignment; only running experiments enroll. Records nothing."""
    experiment = await get_experiment(session, experiment_id)
    index: int | None = None
    if experiment.status == ExperimentStatus.RUNNING:
        index = assignment.assign(
            experiment.salt,
            experiment.traffic_percent,
            [v.weight for v in experiment.variants],
            subject_id,
        )
    variant = experiment.variants[index] if index is not None else None
    return AssignResponse(
        experiment_id=experiment.id,
        subject_id=subject_id,
        enrolled=variant is not None,
        variant=(
            AssignedVariant(key=variant.key, version=variant.version.version)
            if variant is not None
            else None
        ),
    )
