"""Schemas shared across resources."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for API schemas: reject unknown fields, allow ORM attribute loading."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    403: {"model": ErrorResponse, "description": "Insufficient role"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Conflict with current state"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}
