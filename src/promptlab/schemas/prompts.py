"""Schemas for prompts, versions, diffs, labels and rendering."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from promptlab.schemas.common import ApiModel

PROMPT_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
LABEL_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
MAX_TEMPLATE_LENGTH = 100_000
MAX_TAGS = 32
MAX_TAG_LENGTH = 64

PromptName = Annotated[str, Field(pattern=PROMPT_NAME_PATTERN, examples=["support-reply"])]
LabelName = Annotated[str, Field(pattern=LABEL_NAME_PATTERN, examples=["production"])]
VersionRef = int | Literal["latest"]
"""A version number or the alias ``latest``."""


def _dedupe(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


Tag = Annotated[str, StringConstraints(min_length=1, max_length=MAX_TAG_LENGTH)]
Tags = Annotated[
    list[Tag],
    Field(max_length=MAX_TAGS, description="Tags; duplicates are removed preserving order"),
    AfterValidator(_dedupe),
]


class PromptCreate(ApiModel):
    name: PromptName
    description: str = ""
    tags: Tags = Field(default_factory=list)


class PromptUpdate(ApiModel):
    description: str | None = None
    tags: Tags | None = None


class PromptOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    tags: list[str]
    latest_version: int | None = Field(description="Highest version number, null if none")
    labels: dict[str, int] = Field(description="Label name to the version number it points at")
    created_at: datetime
    updated_at: datetime


class VersionCreate(ApiModel):
    template: str = Field(min_length=1, max_length=MAX_TEMPLATE_LENGTH)
    model_settings: dict[str, Any] = Field(
        default_factory=dict, description="Free-form model parameters, e.g. model, temperature"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    commit_message: str = ""


class VersionOut(ApiModel):
    id: uuid.UUID
    prompt: str
    version: int
    template: str
    variables: list[str]
    model_settings: dict[str, Any]
    metadata: dict[str, Any]
    commit_message: str
    content_hash: str
    created_by: str
    created_at: datetime


class VariablesDiff(ApiModel):
    added: list[str]
    removed: list[str]


class ModelSettingsDiff(ApiModel):
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, dict[str, Any]] = Field(
        description='Changed keys mapped to {"from": old, "to": new}'
    )


class DiffOut(ApiModel):
    prompt: str
    from_version: int
    to_version: int
    template_diff: str = Field(description="Unified diff of the templates")
    variables: VariablesDiff
    model_settings: ModelSettingsDiff


class LabelAssign(ApiModel):
    version: int = Field(ge=1)


class LabelOut(ApiModel):
    name: str
    version: int
    updated_by: str
    updated_at: datetime


class LabelEventOut(ApiModel):
    label: str
    from_version: int | None
    to_version: int | None
    actor: str
    created_at: datetime


class RenderRequest(ApiModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    version: int | None = Field(default=None, ge=1)
    label: LabelName | None = None

    @model_validator(mode="after")
    def _version_or_label(self) -> Self:
        if self.version is not None and self.label is not None:
            raise ValueError("Specify at most one of 'version' or 'label'")
        return self


class RenderOut(ApiModel):
    prompt: str
    version: int
    label: str | None
    rendered: str
    model_settings: dict[str, Any]
