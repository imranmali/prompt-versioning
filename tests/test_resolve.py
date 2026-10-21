"""Experiment-aware prompt resolution."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from promptlab.config import Settings
from promptlab.db import Base
from promptlab.main import create_app
from promptlab.models import Experiment, ExperimentStatus
from promptlab.services import assignment
from promptlab.services.resolution import PromptSnapshot
from tests.conftest import ADMIN_KEY
from tests.experiment_factories import (
    create_experiment,
    running_experiment,
    seed_prompt,
    stored_events,
    transition,
)

SALT = "resolve-salt"


async def _resolve(client: AsyncClient, name: str = "greet", **body: Any) -> dict[str, Any]:
    response = await client.post(f"/v1/prompts/{name}/resolve", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _expected_variant(subject: str, traffic: int = 100) -> str | None:
    index = assignment.assign(SALT, traffic, [1, 1], subject)
    return None if index is None else ("control", "treatment")[index]


def _subject(enrolled: bool, traffic: int, variant: str | None = None) -> str:
    for i in range(10_000):
        subject = f"user-{i}"
        assigned = _expected_variant(subject, traffic)
        if enrolled and assigned is not None and variant in (None, assigned):
            return subject
        if not enrolled and assigned is None:
            return subject
    raise AssertionError("no matching subject")  # pragma: no cover


async def test_enrolled_subject(
    app: FastAPI, client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await seed_prompt(app, model_settings=[{"temperature": 0.1}, {"temperature": 0.9}, {}])
    experiment = await running_experiment(
        client,
        salt=SALT,
        variants=[{"key": "control", "version": 1}, {"key": "treatment", "version": 2}],
    )
    subject = _subject(enrolled=True, traffic=100, variant="treatment")
    body = await _resolve(runtime_client, subject_id=subject)
    assert body == {
        "prompt": "greet",
        "version": 2,
        "label": None,
        "template": "Hi {{ name }} (v2)",
        "model_settings": {"temperature": 0.9},
        "rendered": None,
        "experiment": {"id": experiment["id"], "name": "greeting-test", "variant": "treatment"},
    }
    # Sticky: the same subject resolves the same way, consistent with /assign.
    assert (await _resolve(runtime_client, subject_id=subject))["version"] == 2
    assigned = await client.post(
        f"/v1/experiments/{experiment['id']}/assign", json={"subject_id": subject}
    )
    assert assigned.json()["variant"] == {"key": "treatment", "version": 2}


async def test_no_experiment(app: FastAPI, runtime_client: AsyncClient) -> None:
    await seed_prompt(app, labels={"production": 2, "staging": 3})
    body = await _resolve(runtime_client, label="production", subject_id="alice")
    assert body["version"] == 2
    assert body["label"] == "production"
    assert body["experiment"] is None
    assert body["template"] == "Hi {{ name }} (v2)"
    assert (await _resolve(runtime_client))["version"] == 2  # label defaults to production
    assert (await _resolve(runtime_client, label="staging"))["version"] == 3


async def test_unknown_label(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    response = await client.post("/v1/prompts/greet/resolve", json={"label": "canary"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_unknown_prompt(client: AsyncClient) -> None:
    response = await client.post("/v1/prompts/missing/resolve", json={"subject_id": "a"})
    assert response.status_code == 404


async def test_exposure_counted(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, salt=SALT)
    subject = _subject(enrolled=True, traffic=100)
    variant = _expected_variant(subject)
    await _resolve(client, subject_id=subject)

    results = (await client.get(f"/v1/experiments/{experiment['id']}/results")).json()
    exposures = {v["key"]: v["exposures"] for v in results["variants"]}
    assert results["total_exposures"] == 1
    assert exposures[variant or ""] == 1
    # Repeated resolves record more events but the subject is counted once.
    await _resolve(client, subject_id=subject)
    assert len(await stored_events(app, experiment["id"])) == 2
    results = (await client.get(f"/v1/experiments/{experiment['id']}/results")).json()
    assert results["total_exposures"] == 1


async def test_record_exposure_disabled(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, salt=SALT)
    body = await _resolve(client, subject_id="alice", record_exposure=False)
    assert body["experiment"] is not None
    assert await stored_events(app, experiment["id"]) == []


async def test_rendered_output(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app, templates=["Hi {{ name }}"])
    body = await _resolve(client, variables={"name": "Ada"})
    assert body["rendered"] == "Hi Ada"


async def test_rendered_variant(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await running_experiment(client, salt=SALT)
    subject = _subject(enrolled=True, traffic=100, variant="control")
    body = await _resolve(client, subject_id=subject, variables={"name": "Ada"})
    assert body["rendered"] == "Hello Ada (v1)"


async def test_render_errors_propagate(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app, templates=["Hi {{ name }}", "{% if %}"], labels={"production": 1})
    missing = await client.post("/v1/prompts/greet/resolve", json={"variables": {}})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "missing_variables"

    experiment = await running_experiment(client, salt=SALT)
    subject = _subject(enrolled=True, traffic=100, variant="treatment")
    broken = await client.post(
        "/v1/prompts/greet/resolve", json={"subject_id": subject, "variables": {}}
    )
    assert broken.status_code == 422
    assert broken.json()["error"]["code"] == "invalid_template"
    # A failed render records no exposure.
    assert await stored_events(app, experiment["id"]) == []


async def test_not_enrolled_subject_gets_fallback_label(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app, labels={"production": 1, "stable": 3})
    experiment = await running_experiment(
        client, salt=SALT, traffic_percent=10, fallback_label="stable"
    )
    outsider = _subject(enrolled=False, traffic=10)
    body = await _resolve(client, subject_id=outsider)
    assert (body["version"], body["label"], body["experiment"]) == (3, "stable", None)
    # Without a subject the experiment's fallback label applies as well.
    assert (await _resolve(client))["label"] == "stable"
    # An explicit label always wins over the experiment's fallback label.
    explicit = await _resolve(client, subject_id=outsider, label="production")
    assert (explicit["version"], explicit["label"]) == (1, "production")
    assert await stored_events(app, experiment["id"]) == []


async def test_paused_or_draft_experiment_is_ignored(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, salt=SALT)
    await create_experiment(client, name="draft")
    await transition(client, experiment["id"], "pause")
    body = await _resolve(client, subject_id="alice")
    assert (body["version"], body["label"], body["experiment"]) == (1, "production", None)


async def test_resolve_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    for payload in (
        {"subject_id": ""},
        {"label": "Not A Label"},
        {"variables": ["a"]},
        {"unexpected": 1},
    ):
        response = await client.post("/v1/prompts/greet/resolve", json=payload)
        assert response.status_code == 422, payload


async def test_resolve_requires_api_key(app: FastAPI, anon_client: AsyncClient) -> None:
    await seed_prompt(app)
    assert (await anon_client.post("/v1/prompts/greet/resolve", json={})).status_code == 401


# ---------------------------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def cached_app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings.model_copy(update={"resolve_cache_ttl_seconds": 60}))
    engine = application.state.engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield application
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def cached_client(cached_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=cached_app),
        base_url="http://test",
        headers={"X-API-Key": ADMIN_KEY},
    ) as c:
        yield c


async def _set_status_behind_api(
    app: FastAPI, experiment_id: str, status: ExperimentStatus
) -> None:
    async with app.state.session_factory() as session:
        await session.execute(
            update(Experiment)
            .where(Experiment.id == uuid.UUID(experiment_id))
            .values(status=status)
        )
        await session.commit()


async def test_resolve_cache_and_invalidation(
    cached_app: FastAPI, cached_client: AsyncClient
) -> None:
    await seed_prompt(cached_app)
    cache = cached_app.state.resolve_cache
    subject = _subject(enrolled=True, traffic=100)

    # No experiment yet: the snapshot (without experiment) is cached.
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is None
    snapshot = cache.get("greet")
    assert isinstance(snapshot, PromptSnapshot)
    assert snapshot.experiment is None

    # Starting an experiment invalidates the entry: the next resolve sees it immediately.
    experiment = await running_experiment(cached_client, salt=SALT)
    assert cache.get("greet") is None
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is not None
    snapshot = cache.get("greet")
    assert isinstance(snapshot, PromptSnapshot)
    assert snapshot.experiment is not None
    assert snapshot.experiment.id == uuid.UUID(experiment["id"])

    # Changing the database behind the API's back is not visible until the TTL expires:
    # proof that resolution is served from the cache.
    await _set_status_behind_api(cached_app, experiment["id"], ExperimentStatus.PAUSED)
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is not None
    await _set_status_behind_api(cached_app, experiment["id"], ExperimentStatus.RUNNING)

    # Lifecycle changes through the API invalidate the entry.
    await transition(cached_client, experiment["id"], "pause")
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is None
    await transition(cached_client, experiment["id"], "start")
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is not None
    patched = await cached_client.patch(
        f"/v1/experiments/{experiment['id']}", json={"description": "x"}
    )
    assert patched.status_code == 200
    assert cache.get("greet") is None
    await _resolve(cached_client, subject_id=subject)
    await transition(cached_client, experiment["id"], "complete")
    assert cache.get("greet") is None
    assert (await _resolve(cached_client, subject_id=subject))["experiment"] is None

    # Exposures were still recorded for every enrolled resolve.
    exposures = list(await stored_events(cached_app, experiment["id"]))
    assert len(exposures) == 4


async def test_cached_snapshot_is_immutable(
    cached_app: FastAPI, cached_client: AsyncClient
) -> None:
    await seed_prompt(cached_app, model_settings=[{"temperature": 0.5}, {"temperature": 0.7}, {}])
    await running_experiment(cached_client, salt=SALT)
    subject = _subject(enrolled=True, traffic=100)
    first = await _resolve(cached_client, subject_id=subject)
    snapshot = cached_app.state.resolve_cache.get("greet")
    assert isinstance(snapshot, PromptSnapshot)
    assert snapshot.experiment is not None
    with pytest.raises(TypeError):
        snapshot.experiment.variants[0].model_settings["temperature"] = 2.0  # type: ignore[index]
    second = await _resolve(cached_client, subject_id=subject)
    assert first["model_settings"] == second["model_settings"]
