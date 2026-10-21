from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from promptlab.schemas.common import ApiModel
from promptlab.schemas.experiments import LabelName


class ResolveRequest(ApiModel):
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)
    label: LabelName = "production"
    variables: dict[str, Any] | None = Field(
        default=None, description="When given, the resolved template is rendered with them"
    )
    record_exposure: bool = True


class ResolvedExperiment(ApiModel):
    id: uuid.UUID
    name: str
    variant: str


class ResolveResponse(ApiModel):
    prompt: str
    version: int
    label: str | None = Field(description="Label used, null when an experiment variant applied")
    template: str
    model_settings: dict[str, Any]
    rendered: str | None
    experiment: ResolvedExperiment | None
