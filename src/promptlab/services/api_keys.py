"""API key lifecycle."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.db import utcnow
from promptlab.errors import NotFoundError
from promptlab.models import ApiKey, Role
from promptlab.security import generate_api_key, hash_api_key, key_display_prefix


async def create_api_key(session: AsyncSession, name: str, role: Role) -> tuple[ApiKey, str]:
    """Create a key and return the record together with its plaintext (shown once)."""
    plaintext = generate_api_key()
    record = ApiKey(
        name=name,
        role=role,
        prefix=key_display_prefix(plaintext),
        key_hash=hash_api_key(plaintext),
    )
    session.add(record)
    await session.commit()
    return record, plaintext


async def list_api_keys(session: AsyncSession, limit: int, offset: int) -> tuple[list[ApiKey], int]:
    total = await session.scalar(select(func.count()).select_from(ApiKey)) or 0
    rows = await session.scalars(
        select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id).limit(limit).offset(offset)
    )
    return list(rows), total


async def revoke_api_key(session: AsyncSession, key_id: uuid.UUID) -> None:
    record = await session.get(ApiKey, key_id)
    if record is None:
        raise NotFoundError(f"API key '{key_id}' not found")
    if record.revoked_at is None:
        record.revoked_at = utcnow()
        await session.commit()
