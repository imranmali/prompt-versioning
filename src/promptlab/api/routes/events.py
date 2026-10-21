"""Events endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import get_session
from promptlab.schemas.common import ERROR_RESPONSES
from promptlab.schemas.events import EventBatch, EventBatchResult
from promptlab.security import require_runtime
from promptlab.services import analytics

router = APIRouter(
    tags=["events"], dependencies=[Depends(require_runtime)], responses=ERROR_RESPONSES
)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=EventBatchResult)
async def ingest_events(
    body: EventBatch, session: AsyncSession = Depends(get_session)
) -> EventBatchResult:
    """Ingest up to 1000 exposure/metric events; retries with the same `event_id` are no-ops."""
    return await analytics.ingest_events(session, body.events)
