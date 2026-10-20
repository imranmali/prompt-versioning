"""API key generation, hashing and role-based authorization dependencies."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.api.deps import get_session, get_settings_dep
from promptlab.config import Settings
from promptlab.db import utcnow
from promptlab.errors import ForbiddenError, UnauthorizedError
from promptlab.models import ApiKey, Role

API_KEY_PREFIX = "pl_"
LAST_USED_RESOLUTION = timedelta(minutes=1)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyHeader")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerToken")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller of a request."""

    name: str
    role: Role
    key_id: uuid.UUID | None = None


def generate_api_key() -> str:
    """Return a new random API key (256 bits of entropy)."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_display_prefix(key: str) -> str:
    return key[: len(API_KEY_PREFIX) + 6]


def _extract_key(header_key: str | None, bearer: HTTPAuthorizationCredentials | None) -> str | None:
    if header_key:
        return header_key
    if bearer and bearer.scheme.lower() == "bearer" and bearer.credentials:
        return bearer.credentials
    return None


async def get_principal(
    request: Request,
    header_key: str | None = Depends(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> Principal:
    if not settings.auth_enabled:
        principal = Principal(name="anonymous", role=Role.ADMIN)
        request.state.principal = principal
        return principal

    key = _extract_key(header_key, bearer)
    if not key:
        raise UnauthorizedError("Missing API key")

    bootstrap = settings.bootstrap_admin_key
    bootstrap_key = bootstrap.get_secret_value() if bootstrap is not None else ""
    if bootstrap_key and hmac.compare_digest(key.encode(), bootstrap_key.encode()):
        principal = Principal(name="bootstrap-admin", role=Role.ADMIN)
        request.state.principal = principal
        return principal

    record = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(key)))
    if record is None or record.revoked_at is not None:
        raise UnauthorizedError("Invalid or revoked API key")

    now = utcnow()
    if record.last_used_at is None or now - record.last_used_at > LAST_USED_RESOLUTION:
        record.last_used_at = now
        await session.commit()

    principal = Principal(name=record.name, role=record.role, key_id=record.id)
    request.state.principal = principal
    return principal


def require_role(role: Role) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory enforcing that the caller has at least ``role``."""

    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.role.allows(role):
            raise ForbiddenError(
                f"This operation requires the '{role.value}' role",
                details={"required_role": role.value, "role": principal.role.value},
            )
        return principal

    return dependency


require_runtime = require_role(Role.RUNTIME)
require_editor = require_role(Role.EDITOR)
require_admin = require_role(Role.ADMIN)
