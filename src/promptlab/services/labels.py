"""Deployment labels: movable pointers from a label name to a prompt version."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.errors import NotFoundError
from promptlab.models import LabelEvent, Prompt, PromptLabel, PromptVersion


async def find_label(session: AsyncSession, prompt: Prompt, label: str) -> PromptLabel | None:
    return await session.scalar(
        select(PromptLabel).where(PromptLabel.prompt_id == prompt.id, PromptLabel.name == label)
    )


async def get_label_version(session: AsyncSession, prompt: Prompt, label: str) -> PromptVersion:
    """Return the version ``label`` points at or raise ``NotFoundError``."""
    record = await find_label(session, prompt, label)
    if record is None:
        raise NotFoundError(f"Label '{label}' not found on prompt '{prompt.name}'")
    return record.version


async def move_label(
    session: AsyncSession,
    prompt: Prompt,
    label: str,
    version: PromptVersion | None,
    actor: str,
) -> PromptLabel | None:
    """Point ``label`` at ``version`` (``None`` deletes it) and append a history entry.

    Does not commit: callers own the transaction so label moves can be combined with other
    changes atomically (e.g. completing an experiment and promoting its winner).
    Returns the label row, or ``None`` when the label was deleted. Moving a label to the version
    it already points at is a no-op and records no history.
    """
    record = await find_label(session, prompt, label)
    from_version = record.version.version if record is not None else None
    to_version = version.version if version is not None else None
    if from_version == to_version:
        return record

    result: PromptLabel | None
    if version is None:
        await session.delete(record)  # from_version != to_version implies the label exists
        result = None
    elif record is None:
        result = PromptLabel(prompt_id=prompt.id, name=label, version=version, updated_by=actor)
        session.add(result)
    else:
        record.version = version
        record.updated_by = actor
        result = record

    session.add(
        LabelEvent(
            prompt_id=prompt.id,
            label=label,
            from_version=from_version,
            to_version=to_version,
            actor=actor,
        )
    )
    await session.flush()
    return result
