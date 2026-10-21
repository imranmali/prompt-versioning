"""Event ingestion and per-variant experiment results.

Results are aggregated in SQL (``COUNT``/``SUM`` per variant); events are never loaded into memory.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, distinct, exists, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from promptlab.db import utcnow
from promptlab.errors import ConflictError, UnprocessableError
from promptlab.models import EXPOSURE_EVENT, Event, Experiment, ExperimentStatus, ExperimentVariant
from promptlab.schemas.events import EventBatchResult, EventIn
from promptlab.schemas.experiments import (
    BinaryVariantResult,
    ExperimentResults,
    MetricKind,
    NumericVariantResult,
    SampleRatioMismatch,
)
from promptlab.services import assignment, stats
from promptlab.services.experiments import get_experiment

logger = logging.getLogger(__name__)

SRM_THRESHOLD = 0.001
"""Sample-ratio-mismatch is flagged when the chi-square p-value is below this threshold."""
INGEST_ATTEMPTS = 3
_ACCEPTING_STATUSES = frozenset({ExperimentStatus.RUNNING, ExperimentStatus.PAUSED})

# --------------------------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ExperimentInfo:
    status: ExperimentStatus
    salt: str
    traffic_percent: int
    variant_ids: tuple[uuid.UUID, ...]
    variant_keys: tuple[str, ...]
    weights: tuple[int, ...]


async def _load_experiments(
    session: AsyncSession, ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, _ExperimentInfo]:
    rows = await session.scalars(
        select(Experiment).options(selectinload(Experiment.variants)).where(Experiment.id.in_(ids))
    )
    return {
        e.id: _ExperimentInfo(
            status=e.status,
            salt=e.salt,
            traffic_percent=e.traffic_percent,
            variant_ids=tuple(v.id for v in e.variants),
            variant_keys=tuple(v.key for v in e.variants),
            weights=tuple(v.weight for v in e.variants),
        )
        for e in rows
    }


def _validate_batch(
    events: Sequence[EventIn], experiments: dict[uuid.UUID, _ExperimentInfo]
) -> None:
    unknown = sorted({str(e.experiment_id) for e in events if e.experiment_id not in experiments})
    if unknown:
        raise UnprocessableError(
            "Unknown experiment id(s); no event of the batch was stored",
            details={"unknown_experiments": unknown},
        )
    bad_variants = [
        {"index": i, "experiment_id": str(e.experiment_id), "variant": e.variant}
        for i, e in enumerate(events)
        if e.variant is not None and e.variant not in experiments[e.experiment_id].variant_keys
    ]
    if bad_variants:
        raise UnprocessableError(
            "Unknown variant key(s); no event of the batch was stored",
            details={"unknown_variants": bad_variants},
        )


def _attribute(event: EventIn, info: _ExperimentInfo) -> uuid.UUID | None:
    """Variant id for ``event`` or ``None`` when it must be skipped."""
    if info.status not in _ACCEPTING_STATUSES:
        return None
    if event.variant is not None:
        return info.variant_ids[info.variant_keys.index(event.variant)]
    index = assignment.assign(info.salt, info.traffic_percent, info.weights, event.subject_id)
    return info.variant_ids[index] if index is not None else None


async def existing_event_ids(
    session: AsyncSession, keys: Collection[tuple[uuid.UUID, str]]
) -> set[tuple[uuid.UUID, str]]:
    """The ``(experiment_id, event_id)`` pairs among ``keys`` that are already stored."""
    if not keys:
        return set()
    rows = await session.execute(
        select(Event.experiment_id, Event.event_id).where(
            Event.experiment_id.in_({experiment_id for experiment_id, _ in keys}),
            Event.event_id.in_({event_id for _, event_id in keys}),
        )
    )
    return {(row[0], row[1]) for row in rows if row[1] is not None} & set(keys)


async def ingest_events(session: AsyncSession, events: Sequence[EventIn]) -> EventBatchResult:
    """Validate the batch as a whole, attribute variants and store new events idempotently."""
    experiments = await _load_experiments(session, {e.experiment_id for e in events})
    _validate_batch(events, experiments)

    now = utcnow()
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for event in events:
        variant_id = _attribute(event, experiments[event.experiment_id])
        if variant_id is None:
            skipped += 1
            continue
        candidates.append(
            {
                "experiment_id": event.experiment_id,
                "variant_id": variant_id,
                "subject_id": event.subject_id,
                "name": event.name,
                "value": event.value,
                "event_id": event.event_id,
                "created_at": event.timestamp or now,
            }
        )

    keys = {(c["experiment_id"], c["event_id"]) for c in candidates if c["event_id"] is not None}
    for _attempt in range(INGEST_ATTEMPTS):
        stored = await existing_event_ids(session, keys)
        rows: list[dict[str, Any]] = []
        seen: set[tuple[uuid.UUID, str]] = set()
        for candidate in candidates:
            if candidate["event_id"] is not None:
                key = (candidate["experiment_id"], candidate["event_id"])
                if key in stored or key in seen:
                    continue
                seen.add(key)
            rows.append(candidate)
        try:
            if rows:
                await session.execute(insert(Event), rows)
            await session.commit()
        except IntegrityError:
            # A concurrent request stored some of the same event ids after our pre-select:
            # roll back and recompute the duplicates.
            await session.rollback()
            logger.info("event batch raced with a concurrent insert; retrying")
            continue
        return EventBatchResult(
            accepted=len(rows), duplicates=len(candidates) - len(rows), skipped=skipped
        )
    raise ConflictError("Could not store the event batch due to concurrent writes; retry")


# --------------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Moments:
    count: int
    total: float
    total_squares: float


async def _exposures(session: AsyncSession, experiment_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Event.variant_id, func.count(distinct(Event.subject_id)))
        .where(Event.experiment_id == experiment_id, Event.name == EXPOSURE_EVENT)
        .group_by(Event.variant_id)
    )
    return {row[0]: int(row[1]) for row in rows}


async def _conversions(
    session: AsyncSession, experiment_id: uuid.UUID, metric: str
) -> dict[uuid.UUID, int]:
    exposure = aliased(Event)
    exposed_in_same_variant = exists().where(
        and_(
            exposure.experiment_id == Event.experiment_id,
            exposure.variant_id == Event.variant_id,
            exposure.subject_id == Event.subject_id,
            exposure.name == EXPOSURE_EVENT,
        )
    )
    rows = await session.execute(
        select(Event.variant_id, func.count(distinct(Event.subject_id)))
        .where(Event.experiment_id == experiment_id, Event.name == metric, exposed_in_same_variant)
        .group_by(Event.variant_id)
    )
    return {row[0]: int(row[1]) for row in rows}


async def _moments(
    session: AsyncSession, experiment_id: uuid.UUID, metric: str
) -> dict[uuid.UUID, _Moments]:
    rows = await session.execute(
        select(
            Event.variant_id,
            func.count(Event.id),
            func.sum(Event.value),
            func.sum(Event.value * Event.value),
        )
        .where(Event.experiment_id == experiment_id, Event.name == metric)
        .group_by(Event.variant_id)
    )
    return {
        row[0]: _Moments(count=int(row[1]), total=float(row[2]), total_squares=float(row[3]))
        for row in rows
    }


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _lift(value: float | None, control: float | None) -> tuple[float | None, float | None]:
    if value is None or control is None:
        return None, None
    absolute = value - control
    relative = absolute / control if control != 0 else None
    return _finite(absolute), _finite(relative)


def _significant(p_value: float | None, alpha: float) -> bool:
    return p_value is not None and p_value < alpha


def _binary_results(
    variants: Sequence[ExperimentVariant],
    exposures: dict[uuid.UUID, int],
    conversions: dict[uuid.UUID, int],
    alpha: float,
) -> list[BinaryVariantResult]:
    control = next(v for v in variants if v.is_control)
    control_n = exposures.get(control.id, 0)
    control_x = conversions.get(control.id, 0)
    control_rate = control_x / control_n if control_n else None
    results = []
    for v in variants:
        n = exposures.get(v.id, 0)
        x = conversions.get(v.id, 0)
        rate = x / n if n else None
        interval = stats.wilson_interval(x, n, alpha)
        lift_abs = lift_rel = p_value = None
        if not v.is_control:
            lift_abs, lift_rel = _lift(rate, control_rate)
            p_value = stats.two_proportion_z_test(control_x, control_n, x, n)
        results.append(
            BinaryVariantResult(
                key=v.key,
                version=v.version.version,
                is_control=v.is_control,
                exposures=n,
                conversions=x,
                rate=rate,
                ci_low=interval[0] if interval else None,
                ci_high=interval[1] if interval else None,
                lift_abs=lift_abs,
                lift_rel=lift_rel,
                p_value=p_value,
                significant=_significant(p_value, alpha),
            )
        )
    return results


def _mean_std(m: _Moments | None) -> tuple[int, float | None, float | None]:
    if m is None or m.count == 0:
        return 0, None, None
    mean = m.total / m.count
    if m.count < 2:
        return m.count, mean, None
    # Guard against tiny negative values caused by floating point cancellation.
    variance = max(0.0, (m.total_squares - m.total * m.total / m.count) / (m.count - 1))
    return m.count, mean, math.sqrt(variance)


def _numeric_results(
    variants: Sequence[ExperimentVariant],
    exposures: dict[uuid.UUID, int],
    moments: dict[uuid.UUID, _Moments],
    alpha: float,
) -> list[NumericVariantResult]:
    control = next(v for v in variants if v.is_control)
    control_n, control_mean, control_std = _mean_std(moments.get(control.id))
    results = []
    for v in variants:
        n, mean, std = _mean_std(moments.get(v.id))
        interval = (
            stats.t_interval(mean, std, n, alpha) if mean is not None and std is not None else None
        )
        lift_abs = lift_rel = p_value = None
        if not v.is_control:
            lift_abs, lift_rel = _lift(mean, control_mean)
            if (
                mean is not None
                and std is not None
                and control_mean is not None
                and control_std is not None
            ):
                welch = stats.welch_t_test(control_mean, control_std**2, control_n, mean, std**2, n)
                p_value = welch.p_value if welch is not None else None
        results.append(
            NumericVariantResult(
                key=v.key,
                version=v.version.version,
                is_control=v.is_control,
                exposures=exposures.get(v.id, 0),
                count=n,
                mean=_finite(mean),
                std=_finite(std),
                ci_low=_finite(interval[0]) if interval else None,
                ci_high=_finite(interval[1]) if interval else None,
                lift_abs=lift_abs,
                lift_rel=lift_rel,
                p_value=p_value,
                significant=_significant(p_value, alpha),
            )
        )
    return results


def pick_winner(
    results: Sequence[BinaryVariantResult] | Sequence[NumericVariantResult],
) -> str | None:
    """The significant non-control variant with the largest positive absolute lift."""
    best: tuple[float, str] | None = None
    for r in results:
        if r.is_control or not r.significant or r.lift_abs is None or r.lift_abs <= 0:
            continue
        if best is None or r.lift_abs > best[0]:
            best = (r.lift_abs, r.key)
    return best[1] if best is not None else None


async def experiment_results(
    session: AsyncSession,
    experiment_id: uuid.UUID,
    *,
    metric: str | None = None,
    kind: MetricKind = "binary",
    alpha: float = 0.05,
) -> ExperimentResults:
    if metric == EXPOSURE_EVENT:
        raise UnprocessableError(f"'{EXPOSURE_EVENT}' is not a metric")
    experiment = await get_experiment(session, experiment_id)
    metric_name = metric or experiment.primary_metric
    variants = experiment.variants

    exposures = await _exposures(session, experiment.id)
    observed = [exposures.get(v.id, 0) for v in variants]
    srm = stats.sample_ratio_test(observed, [v.weight for v in variants])

    variant_results: list[BinaryVariantResult] | list[NumericVariantResult]
    if kind == "binary":
        conversions = await _conversions(session, experiment.id, metric_name)
        variant_results = _binary_results(variants, exposures, conversions, alpha)
    else:
        moments = await _moments(session, experiment.id, metric_name)
        variant_results = _numeric_results(variants, exposures, moments, alpha)

    return ExperimentResults(
        experiment_id=experiment.id,
        metric=metric_name,
        kind=kind,
        alpha=alpha,
        total_exposures=sum(observed),
        srm=SampleRatioMismatch(
            chi_square=srm.chi_square if srm else None,
            p_value=srm.p_value if srm else None,
            mismatch=srm is not None and srm.p_value < SRM_THRESHOLD,
        ),
        variants=variant_results,
        winner=pick_winner(variant_results),
    )
