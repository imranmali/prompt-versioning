"""Events endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from promptlab.schemas.common import ERROR_RESPONSES

router = APIRouter(tags=["events"], responses=ERROR_RESPONSES)
