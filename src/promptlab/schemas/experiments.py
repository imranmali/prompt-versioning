from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from promptlab.models import EXPOSURE_EVENT, ExperimentStatus
from promptlab.schemas.common import ApiModel

KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
"""Variant keys and label names."""
METRIC_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"
"""Event and metric names."""

VariantKey = Annotated[str, Field(pattern=KEY_PATTERN, examples=["control"])]
LabelName = Annotated[str, Field(pattern=KEY_PATTERN, examples=["production"])]
MetricName = Annotated[str, Field(pattern=METRIC_PATTERN, examples=["conversion"])]
TrafficPercent = Annotated[int, Field(ge=1, le=100)]
Description = Annotated[str, Field(max_length=10_000)]


def _check_metric(value: str | None) -> str | None:
    if value == EXPOSURE_EVENT:
        raise ValueError(f"'{EXPOSURE_EVENT}' is reserved and cannot be used as a metric")
    return value


class VariantIn(ApiModel):
    key: VariantKey
    version: int = Field(ge=1, description="Version number of the experiment's prompt")
    weight: int = Field(default=1, ge=1, le=1_000_000, description="Relative traffic share")
    is_control: bool = False


Variants = Annotated[list[VariantIn], Field(min_length=2, max_length=10)]


class ExperimentCreate(ApiModel):
    prompt: str = Field(min_length=1, max_length=128, description="Name of the prompt")
    name: str = Field(min_length=1, max_length=128)
    description: Description = ""
    variants: Variants
    traffic_percent: TrafficPercent = 100
    primary_metric: MetricName = "conversion"
    fallback_label: LabelName = "production"
    salt: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Hash salt; a random one is generated when omitted",
    )

    _metric = field_validator("primary_metric")(_check_metric)


class ExperimentUpdate(ApiModel):
    """Partial update; omitted (or null) fields are left unchanged."""

    description: Description | None = None
    variants: Variants | None = None
    traffic_percent: TrafficPercent | None = None
    primary_metric: MetricName | None = None
    fallback_label: LabelName | None = None

    _metric = field_validator("primary_metric")(_check_metric)


class ExperimentComplete(ApiModel):
    winner: VariantKey | None = Field(default=None, description="Key of the winning variant")
    promote_label: LabelName | None = Field(
        default=None, description="Label to move to the winner's version (requires `winner`)"
    )


class VariantOut(ApiModel):
    id: uuid.UUID
    key: str
    version: int
    weight: int
    is_control: bool


class ExperimentOut(ApiModel):
    id: uuid.UUID
    prompt: str
    name: str
    description: str
    status: ExperimentStatus
    traffic_percent: int
    primary_metric: str
    fallback_label: str
    salt: str
    variants: list[VariantOut]
    winner: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssignRequest(ApiModel):
    subject_id: str = Field(min_length=1, max_length=255)


class AssignedVariant(ApiModel):
    key: str
    version: int


class AssignResponse(ApiModel):
    experiment_id: uuid.UUID
    subject_id: str
    enrolled: bool
    variant: AssignedVariant | None


MetricKind = Literal["binary", "numeric"]


class SampleRatioMismatch(ApiModel):
    chi_square: float | None
    p_value: float | None
    mismatch: bool


class VariantResultBase(ApiModel):
    key: str
    version: int
    is_control: bool
    exposures: int = Field(description="Distinct subjects with an exposure in this variant")
    ci_low: float | None
    ci_high: float | None
    lift_abs: float | None = Field(description="Difference to control (null for the control)")
    lift_rel: float | None = Field(description="lift_abs relative to the control's value")
    p_value: float | None
    significant: bool


class BinaryVariantResult(VariantResultBase):
    conversions: int = Field(description="Exposed subjects with at least one metric event")
    rate: float | None


class NumericVariantResult(VariantResultBase):
    count: int = Field(description="Number of metric events")
    mean: float | None
    std: float | None


class ExperimentResults(ApiModel):
    experiment_id: uuid.UUID
    metric: str
    kind: MetricKind
    alpha: float
    total_exposures: int
    srm: SampleRatioMismatch
    variants: list[BinaryVariantResult] | list[NumericVariantResult]
    winner: str | None
