"""Prompt registry: prompts, immutable versions, diffs and rendering."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, exists, func, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.db import utcnow
from promptlab.errors import ConflictError
from promptlab.models import Prompt, PromptLabel, PromptVersion
from promptlab.schemas.prompts import (
    DiffOut,
    PromptCreate,
    PromptOut,
    PromptUpdate,
    VersionCreate,
    VersionRef,
)
from promptlab.services import diffing, templating
from promptlab.services.labels import get_label_version
from promptlab.services.lookups import get_prompt, get_version

MAX_VERSION_ATTEMPTS = 5


def content_hash(template: str, model_settings: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``{template, model_settings}``."""
    canonical = json.dumps(
        {"template": template, "model_settings": model_settings},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Prompts -------------------------------------------------------------------------------


async def summarize(session: AsyncSession, prompts: Sequence[Prompt]) -> list[PromptOut]:
    """Attach ``latest_version`` and ``labels`` to ``prompts`` using two batched queries."""
    ids = [p.id for p in prompts]
    latest: dict[uuid.UUID, int] = {}
    labels: defaultdict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    if ids:
        latest_rows = await session.execute(
            select(PromptVersion.prompt_id, func.max(PromptVersion.version))
            .where(PromptVersion.prompt_id.in_(ids))
            .group_by(PromptVersion.prompt_id)
        )
        latest = {prompt_id: number for prompt_id, number in latest_rows}  # noqa: C416
        label_rows = await session.execute(
            select(PromptLabel.prompt_id, PromptLabel.name, PromptVersion.version)
            .join(PromptVersion, PromptLabel.version_id == PromptVersion.id)
            .where(PromptLabel.prompt_id.in_(ids))
            .order_by(PromptLabel.name)
        )
        for prompt_id, label, number in label_rows:
            labels[prompt_id][label] = number
    return [
        PromptOut(
            id=p.id,
            name=p.name,
            description=p.description,
            tags=p.tags,
            latest_version=latest.get(p.id),
            labels=labels.get(p.id, {}),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in prompts
    ]


async def describe_prompt(session: AsyncSession, name: str) -> PromptOut:
    prompt = await get_prompt(session, name)
    return (await summarize(session, [prompt]))[0]


async def _name_taken(session: AsyncSession, name: str) -> bool:
    return await session.scalar(select(Prompt.id).where(Prompt.name == name)) is not None


async def create_prompt(session: AsyncSession, data: PromptCreate) -> PromptOut:
    """Create a prompt; raise ``ConflictError`` when the name is already taken."""
    if await _name_taken(session, data.name):
        raise ConflictError(f"Prompt '{data.name}' already exists")
    prompt = Prompt(name=data.name, description=data.description, tags=data.tags)
    session.add(prompt)
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race with a concurrent create
        await session.rollback()
        raise ConflictError(f"Prompt '{data.name}' already exists") from exc
    return (await summarize(session, [prompt]))[0]


def _has_tag(session: AsyncSession, tag: str) -> ColumnElement[bool]:
    """Portable "tags contains ``tag``" predicate evaluated in SQL.

    PostgreSQL uses JSONB containment (``tags @> '["tag"]'``); other dialects (SQLite) use a
    correlated ``EXISTS`` over ``json_each(tags)``. Both compare exact element values, so tags
    containing quotes or wildcard characters need no escaping.
    """
    if session.get_bind().dialect.name == "postgresql":
        return type_coerce(Prompt.tags, JSONB).contains([tag])
    elements = func.json_each(Prompt.tags).table_valued("value")
    return exists(select(1).select_from(elements).where(elements.c.value == tag))


async def list_prompts(
    session: AsyncSession,
    limit: int,
    offset: int,
    search: str | None = None,
    tag: str | None = None,
) -> tuple[list[PromptOut], int]:
    conditions: list[ColumnElement[bool]] = []
    if search:
        conditions.append(
            Prompt.name.icontains(search, autoescape=True)
            | Prompt.description.icontains(search, autoescape=True)
        )
    if tag:
        conditions.append(_has_tag(session, tag))
    total = await session.scalar(select(func.count()).select_from(Prompt).where(*conditions)) or 0
    rows = await session.scalars(
        select(Prompt).where(*conditions).order_by(Prompt.name).limit(limit).offset(offset)
    )
    return await summarize(session, list(rows)), total


async def update_prompt(session: AsyncSession, name: str, data: PromptUpdate) -> PromptOut:
    """Update description and/or tags; ``null`` or omitted fields are left unchanged."""
    prompt = await get_prompt(session, name)
    if data.description is not None:
        prompt.description = data.description
    if data.tags is not None:
        prompt.tags = data.tags
    if session.is_modified(prompt):
        prompt.updated_at = utcnow()
        await session.commit()
    return (await summarize(session, [prompt]))[0]


# --- Versions ------------------------------------------------------------------------------


async def _lock_prompt(session: AsyncSession, prompt: Prompt) -> None:
    """Serialize version writers of one prompt for the rest of the transaction.

    A no-op ``UPDATE`` takes the row lock on PostgreSQL and the write lock on SQLite, so the
    ``max(version)`` read that follows sees every committed version.
    """
    await session.execute(
        update(Prompt)
        .where(Prompt.id == prompt.id)
        .values(updated_at=Prompt.updated_at)
        .execution_options(synchronize_session=False)
    )


async def _latest_version(session: AsyncSession, prompt: Prompt) -> PromptVersion | None:
    return await session.scalar(
        select(PromptVersion)
        .where(PromptVersion.prompt_id == prompt.id)
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )


async def create_version(
    session: AsyncSession, name: str, data: VersionCreate, actor: str
) -> tuple[PromptVersion, bool]:
    """Create the next version of prompt ``name``.

    Returns ``(version, created)``. When the template and model settings equal the latest
    version's, that version is returned with ``created=False``. Unique-constraint conflicts with
    concurrent writers are retried up to ``MAX_VERSION_ATTEMPTS`` times, then ``ConflictError``.
    """
    variables = templating.validate_template(data.template)
    digest = content_hash(data.template, data.model_settings)
    for _ in range(MAX_VERSION_ATTEMPTS):
        prompt = await get_prompt(session, name)
        await _lock_prompt(session, prompt)
        latest = await _latest_version(session, prompt)
        if latest is not None and latest.content_hash == digest:
            await session.commit()  # releases the lock; nothing was changed
            return latest, False
        version = PromptVersion(
            prompt_id=prompt.id,
            version=(latest.version if latest is not None else 0) + 1,
            template=data.template,
            variables=variables,
            model_settings=data.model_settings,
            metadata_=data.metadata,
            commit_message=data.commit_message,
            content_hash=digest,
            created_by=actor,
        )
        session.add(version)
        prompt.updated_at = utcnow()
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        return version, True
    raise ConflictError(
        f"Could not allocate a version number for prompt '{name}' due to concurrent writes; "
        "retry the request"
    )


async def list_versions(
    session: AsyncSession, name: str, limit: int, offset: int
) -> tuple[list[PromptVersion], int]:
    """Return a page of the versions of prompt ``name``, newest first, and their total."""
    prompt = await get_prompt(session, name)
    condition = PromptVersion.prompt_id == prompt.id
    total = await session.scalar(select(func.count()).select_from(PromptVersion).where(condition))
    rows = await session.scalars(
        select(PromptVersion)
        .where(condition)
        .order_by(PromptVersion.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def fetch_version(session: AsyncSession, name: str, ref: VersionRef) -> PromptVersion:
    prompt = await get_prompt(session, name)
    return await get_version(session, prompt, ref)


async def diff(session: AsyncSession, name: str, old: VersionRef, new: VersionRef) -> DiffOut:
    prompt = await get_prompt(session, name)
    return diffing.diff_versions(
        prompt.name,
        await get_version(session, prompt, old),
        await get_version(session, prompt, new),
    )


# --- Rendering -----------------------------------------------------------------------------


async def render(
    session: AsyncSession,
    name: str,
    variables: Mapping[str, Any],
    version: int | None = None,
    label: str | None = None,
) -> tuple[PromptVersion, str]:
    """Render the given version, the version ``label`` points at, or the latest version."""
    prompt = await get_prompt(session, name)
    if label is not None:
        target = await get_label_version(session, prompt, label)
    else:
        target = await get_version(session, prompt, version if version is not None else "latest")
    return target, templating.render(target.template, variables)
