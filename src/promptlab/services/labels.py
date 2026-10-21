"""Deployment labels: movable pointers from a label name to a prompt version."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.errors import ConflictError, NotFoundError
from promptlab.models import LabelEvent, Prompt, PromptLabel, PromptVersion
from promptlab.services.lookups import get_prompt, get_version


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


async def list_labels(session: AsyncSession, name: str) -> list[PromptLabel]:
    """Return the labels of prompt ``name`` ordered by label name."""
    prompt = await get_prompt(session, name)
    rows = await session.scalars(
        select(PromptLabel).where(PromptLabel.prompt_id == prompt.id).order_by(PromptLabel.name)
    )
    return list(rows)


async def set_label(
    session: AsyncSession, name: str, label: str, version_number: int, actor: str
) -> PromptLabel:
    """Point ``label`` at version ``version_number`` (creating it if needed) and commit."""
    prompt = await get_prompt(session, name)
    version = await get_version(session, prompt, version_number)
    record = await move_label(session, prompt, label, version, actor)
    await session.commit()
    if record is None:  # pragma: no cover - moving to a version always yields a label row
        raise NotFoundError(f"Label '{label}' not found on prompt '{prompt.name}'")
    return record


async def delete_label(session: AsyncSession, name: str, label: str, actor: str) -> None:
    """Delete ``label`` (recording the move to ``None``) or raise ``NotFoundError``."""
    prompt = await get_prompt(session, name)
    if await find_label(session, prompt, label) is None:
        raise NotFoundError(f"Label '{label}' not found on prompt '{prompt.name}'")
    await move_label(session, prompt, label, None, actor)
    await session.commit()


async def label_history(
    session: AsyncSession, name: str, label: str, limit: int, offset: int
) -> tuple[list[LabelEvent], int]:
    """Return the history of ``label``, newest first (empty for a label that never existed)."""
    prompt = await get_prompt(session, name)
    conditions = (LabelEvent.prompt_id == prompt.id, LabelEvent.label == label)
    total = await session.scalar(select(func.count()).select_from(LabelEvent).where(*conditions))
    rows = await session.scalars(
        select(LabelEvent)
        .where(*conditions)
        .order_by(LabelEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def rollback_label(session: AsyncSession, name: str, label: str, actor: str) -> PromptLabel:
    """Move ``label`` back to the version it pointed at before its most recent move.

    The rollback is itself recorded, so rolling back twice returns to the original version.
    Raises ``ConflictError`` when the label does not exist or has no previous version.
    """
    prompt = await get_prompt(session, name)
    if await find_label(session, prompt, label) is None:
        raise ConflictError(f"Label '{label}' does not exist on prompt '{prompt.name}'")
    last = await session.scalar(
        select(LabelEvent)
        .where(LabelEvent.prompt_id == prompt.id, LabelEvent.label == label)
        .order_by(LabelEvent.id.desc())
        .limit(1)
    )
    if last is None or last.from_version is None:
        raise ConflictError(f"Label '{label}' has no previous version to roll back to")
    target = await get_version(session, prompt, last.from_version)
    record = await move_label(session, prompt, label, target, actor)
    await session.commit()
    if record is None:  # pragma: no cover - moving to a version always yields a label row
        raise NotFoundError(f"Label '{label}' not found on prompt '{prompt.name}'")
    return record
