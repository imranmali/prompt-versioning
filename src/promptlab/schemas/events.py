from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from promptlab.schemas.common import ApiModel
from promptlab.schemas.experiments import MetricName, VariantKey

MAX_BATCH_SIZE = 1000


class EventIn(ApiModel):
    experiment_id: uuid.UUID
    subject_id: str = Field(min_length=1, max_length=255)
    name: MetricName = Field(description="`exposure` or a metric name")
    value: float = Field(default=1.0, allow_inf_nan=False)
    variant: VariantKey | None = Field(
        default=None, description="Variant key; derived from the subject's assignment if omitted"
    )
    event_id: str | None = Field(
        default=None, min_length=1, max_length=128, description="Client id for deduplication"
    )
    timestamp: datetime | None = Field(default=None, description="Defaults to the ingestion time")


class EventBatch(ApiModel):
    events: list[EventIn] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class EventBatchResult(ApiModel):
    accepted: int
    duplicates: int
    skipped: int
