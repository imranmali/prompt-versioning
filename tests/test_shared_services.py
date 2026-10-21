from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.errors import NotFoundError
from promptlab.models import LabelEvent, Prompt, PromptVersion
from promptlab.services.labels import get_label_version, move_label
from promptlab.services.lookups import get_prompt, get_version


async def _seed(session: AsyncSession) -> tuple[Prompt, PromptVersion, PromptVersion]:
    prompt = Prompt(name="greet")
    v1 = PromptVersion(prompt=prompt, version=1, template="Hi", content_hash="a")
    v2 = PromptVersion(prompt=prompt, version=2, template="Hello", content_hash="b")
    session.add_all([prompt, v1, v2])
    await session.commit()
    return prompt, v1, v2


async def test_lookups(session: AsyncSession) -> None:
    prompt, _, v2 = await _seed(session)
    assert (await get_prompt(session, "greet")).id == prompt.id
    assert (await get_version(session, prompt, "latest")).id == v2.id
    assert (await get_version(session, prompt, 1)).version == 1
    with pytest.raises(NotFoundError):
        await get_prompt(session, "missing")
    with pytest.raises(NotFoundError):
        await get_version(session, prompt, 3)


async def test_move_label_records_history(session: AsyncSession) -> None:
    prompt, v1, v2 = await _seed(session)
    with pytest.raises(NotFoundError):
        await get_label_version(session, prompt, "production")

    await move_label(session, prompt, "production", v1, "alice")
    await move_label(session, prompt, "production", v1, "alice")  # no-op
    await move_label(session, prompt, "production", v2, "bob")
    await session.commit()
    assert (await get_label_version(session, prompt, "production")).version == 2

    assert await move_label(session, prompt, "production", None, "carol") is None
    await session.commit()
    with pytest.raises(NotFoundError):
        await get_label_version(session, prompt, "production")

    events = (await session.scalars(select(LabelEvent).order_by(LabelEvent.id))).all()
    assert [(e.from_version, e.to_version, e.actor) for e in events] == [
        (None, 1, "alice"),
        (1, 2, "bob"),
        (2, None, "carol"),
    ]
