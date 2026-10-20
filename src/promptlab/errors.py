"""Error types and handlers producing the uniform ``{"error": {...}}`` envelope."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


class ApiError(Exception):
    """Base class for errors that map to an HTTP response."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        details: Any = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class UnauthorizedError(ApiError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    code = "conflict"


class InvalidStateError(ConflictError):
    code = "invalid_state"


class UnprocessableError(ApiError):
    status_code = 422
    code = "validation_error"


class InvalidTemplateError(UnprocessableError):
    code = "invalid_template"


class MissingVariablesError(UnprocessableError):
    code = "missing_variables"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": _request_id(request),
        }
    }
    return JSONResponse(
        status_code=status_code, content=body, headers=dict(headers) if headers else None
    )


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - registered per type
        raise exc
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details, headers)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - registered per type
        raise exc
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return error_response(request, 422, "validation_error", "Request validation failed", details)


async def _handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - registered per type
        raise exc
    code = _STATUS_CODES.get(exc.status_code, "error")
    try:
        default_message = HTTPStatus(exc.status_code).phrase
    except ValueError:
        default_message = "Error"
    message = exc.detail if isinstance(exc.detail, str) else default_message
    return error_response(request, exc.status_code, code, message, None, exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers for API, validation and HTTP errors.

    Unexpected exceptions are converted to ``internal_error`` responses by
    ``RequestContextMiddleware`` so that they still carry a request id.
    """
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
