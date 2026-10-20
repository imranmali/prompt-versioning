from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from promptlab.models import Role
from promptlab.schemas.common import ApiModel


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    role: Role = Role.RUNTIME


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    role: Role
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Plaintext API key. Shown only once; store it securely.")
