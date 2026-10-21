"""Helpers for experiment tests.

Prompts, versions and labels are created directly through the ORM (the prompt CRUD endpoints are
not part of this change); experiments go through the HTTP API.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import insert, select

from promptlab.models import EXPOSURE_EVENT, Event, Prompt, PromptVersion
from promptlab.services.labels import find_label, move_label
from promptlab.services.lookups import get_prompt, get_version

DEFAULT_TEMPLATES = ("Hello {{ name }} (v1)", "Hi {{ name }} (v2)", "Hey {{ name }} (v3)")


@dataclass(frozen=True)
class SeededPrompt:
    name: str
    versions: tuple[int, ...]
    labels: Mapping[str, int] = field(default_factory=dict)


async def seed_prompt(
    app: FastAPI,
    name: str = "greet",
    templates: Sequence[str] = DEFAULT_TEMPLATES,
    labels: Mapping[str, int] | None = None,
    model_settings: Sequence[Mapping[str, Any]] | None = None,
) -> SeededPrompt:
    """Create prompt ``name`` with one version per template (numbered from 1) and labels.

    ``labels`` defaults to ``{"production": 1}``.
    """
    labels = {"production": 1} if labels is None else labels
    async with app.state.session_factory() as session:
        prompt = Prompt(name=name)
        session.add(prompt)
        for i, template in enumerate(templates, start=1):
            session.add(
                PromptVersion(
                    prompt=prompt,
                    version=i,
                    template=template,
                    model_settings=dict(model_settings[i - 1]) if model_settings else {},
                    content_hash=hashlib.sha256(template.encode()).hexdigest(),
                )
            )
        await session.flush()
        for label, number in labels.items():
            await move_label(session, prompt, label, await get_version(session, prompt, number), "")
        await session.commit()
    return SeededPrompt(name=name, versions=tuple(range(1, len(templates) + 1)), labels=labels)


async def label_version(app: FastAPI, prompt_name: str, label: str) -> int | None:
    """Version number ``label`` points at (``None`` when the label does not exist)."""
    async with app.state.session_factory() as session:
        prompt = await get_prompt(session, prompt_name)
        record = await find_label(session, prompt, label)
        return record.version.version if record is not None else None


def variants(*specs: tuple[str, int, int], control: str | None = None) -> list[dict[str, Any]]:
    """Variant payloads from ``(key, version, weight)`` tuples."""
    return [
        {"key": key, "version": version, "weight": weight, "is_control": key == control}
        for key, version, weight in specs
    ]


def experiment_payload(prompt: str = "greet", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "name": "greeting-test",
        "variants": variants(("control", 1, 50), ("treatment", 2, 50)),
    }
    payload.update(overrides)
    return payload


async def create_experiment(
    client: AsyncClient, prompt: str = "greet", **overrides: Any
) -> dict[str, Any]:
    response = await client.post("/v1/experiments", json=experiment_payload(prompt, **overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def transition(client: AsyncClient, experiment_id: str, action: str) -> dict[str, Any]:
    response = await client.post(f"/v1/experiments/{experiment_id}/{action}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def running_experiment(
    client: AsyncClient, prompt: str = "greet", **overrides: Any
) -> dict[str, Any]:
    experiment = await create_experiment(client, prompt, **overrides)
    return await transition(client, experiment["id"], "start")


def variant_ids(experiment: Mapping[str, Any]) -> dict[str, uuid.UUID]:
    return {v["key"]: uuid.UUID(v["id"]) for v in experiment["variants"]}


async def insert_events(app: FastAPI, rows: Iterable[Mapping[str, Any]]) -> None:
    """Bulk insert raw event rows (keys: experiment_id, variant_id, subject_id, name, value)."""
    batch = [{"value": 1.0, **row} for row in rows]
    if not batch:
        return
    async with app.state.session_factory() as session:
        await session.execute(insert(Event), batch)
        await session.commit()


async def seed_binary(
    app: FastAPI,
    experiment: Mapping[str, Any],
    counts: Mapping[str, tuple[int, int]],
    metric: str = "conversion",
) -> None:
    """Per variant key, expose ``n`` subjects and convert the first ``x``: ``{key: (n, x)}``."""
    ids = variant_ids(experiment)
    experiment_id = uuid.UUID(experiment["id"])
    rows: list[dict[str, Any]] = []
    for key, (exposed, converted) in counts.items():
        for i in range(exposed):
            subject = f"{key}-s{i}"
            base = {"experiment_id": experiment_id, "variant_id": ids[key], "subject_id": subject}
            rows.append({**base, "name": EXPOSURE_EVENT})
            if i < converted:
                rows.append({**base, "name": metric})
    await insert_events(app, rows)


async def seed_numeric(
    app: FastAPI,
    experiment: Mapping[str, Any],
    values: Mapping[str, Sequence[float]],
    metric: str = "rating",
) -> None:
    """Expose one subject per value and record ``metric`` with that value."""
    ids = variant_ids(experiment)
    experiment_id = uuid.UUID(experiment["id"])
    rows: list[dict[str, Any]] = []
    for key, samples in values.items():
        for i, value in enumerate(samples):
            base = {
                "experiment_id": experiment_id,
                "variant_id": ids[key],
                "subject_id": f"{key}-s{i}",
            }
            rows.append({**base, "name": EXPOSURE_EVENT})
            rows.append({**base, "name": metric, "value": value})
    await insert_events(app, rows)


async def stored_events(app: FastAPI, experiment_id: str) -> list[Event]:
    async with app.state.session_factory() as session:
        rows = await session.scalars(
            select(Event).where(Event.experiment_id == uuid.UUID(experiment_id)).order_by(Event.id)
        )
        return list(rows)
