"""Lookups shared by several services."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.errors import NotFoundError
from promptlab.models import Prompt, PromptVersion

VersionRef = int | Literal["latest"]


async def get_prompt(session: AsyncSession, name: str) -> Prompt:
    """Return the prompt called ``name`` or raise ``NotFoundError``."""
    prompt = await session.scalar(select(Prompt).where(Prompt.name == name))
    if prompt is None:
        raise NotFoundError(f"Prompt '{name}' not found")
    return prompt


async def get_version(session: AsyncSession, prompt: Prompt, ref: VersionRef) -> PromptVersion:
    """Return version ``ref`` (number or ``"latest"``) of ``prompt``; raise ``NotFoundError``."""
    query = select(PromptVersion).where(PromptVersion.prompt_id == prompt.id)
    if ref == "latest":
        query = query.order_by(PromptVersion.version.desc()).limit(1)
    else:
        query = query.where(PromptVersion.version == ref)
    version = await session.scalar(query)
    if version is None:
        raise NotFoundError(f"Version '{ref}' of prompt '{prompt.name}' not found")
    return version
