"""Batched, idempotent event ingestion with variant attribution."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.services import analytics, assignment
from tests.experiment_factories import (
    create_experiment,
    running_experiment,
    seed_prompt,
    stored_events,
    transition,
    variant_ids,
)


def _event(experiment: dict[str, Any], subject: str, **fields: Any) -> dict[str, Any]:
    return {"experiment_id": experiment["id"], "subject_id": subject, **fields}


async def _post(client: AsyncClient, events: list[dict[str, Any]]) -> dict[str, int]:
    response = await client.post("/v1/events", json={"events": events})
    assert response.status_code == 202, response.text
    body: dict[str, int] = response.json()
    return body


async def test_accept_batch(app: FastAPI, client: AsyncClient, runtime_client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    events = [
        _event(experiment, "alice", name="exposure"),
        _event(experiment, "alice", name="conversion"),
        _event(experiment, "bob", name="revenue", value=12.5, variant="treatment"),
    ]
    response = await runtime_client.post("/v1/events", json={"events": events})
    assert response.status_code == 202
    assert response.json() == {"accepted": 3, "duplicates": 0, "skipped": 0}
    stored = await stored_events(app, experiment["id"])
    assert [(e.subject_id, e.name, e.value) for e in stored] == [
        ("alice", "exposure", 1.0),
        ("alice", "conversion", 1.0),
        ("bob", "revenue", 12.5),
    ]
    assert stored[2].variant_id == variant_ids(experiment)["treatment"]
    assert all(e.event_id is None for e in stored)


async def test_oversized_batch(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    events = [_event(experiment, f"s{i}", name="exposure") for i in range(1001)]
    response = await client.post("/v1/events", json={"events": events})
    assert response.status_code == 422
    assert await stored_events(app, experiment["id"]) == []
    # Exactly 1000 is accepted.
    assert (await _post(client, events[:1000]))["accepted"] == 1000


async def test_empty_batch_rejected(client: AsyncClient) -> None:
    assert (await client.post("/v1/events", json={"events": []})).status_code == 422


async def test_unknown_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    ghost = str(uuid.uuid4())
    events = [
        _event(experiment, "alice", name="exposure"),
        {"experiment_id": ghost, "subject_id": "bob", "name": "exposure"},
    ]
    response = await client.post("/v1/events", json={"events": events})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"unknown_experiments": [ghost]}
    assert await stored_events(app, experiment["id"]) == []


async def test_unknown_variant_key(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    events = [
        _event(experiment, "alice", name="exposure"),
        _event(experiment, "bob", name="exposure", variant="ghost"),
    ]
    response = await client.post("/v1/events", json={"events": events})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown_variants"] == [
        {"index": 1, "experiment_id": experiment["id"], "variant": "ghost"}
    ]
    assert await stored_events(app, experiment["id"]) == []


async def test_event_field_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    invalid = [
        {"name": "Bad Name"},
        {"name": "exposure", "subject_id": ""},
        {"name": "exposure", "event_id": "x" * 129},
        {"name": "exposure", "variant": "Not A Key"},
        {"name": "exposure", "extra": 1},
        {"name": "revenue", "value": "NaN"},
        {"name": "revenue", "value": "Infinity"},
    ]
    for fields in invalid:
        event = {"experiment_id": experiment["id"], "subject_id": "alice", **fields}
        response = await client.post("/v1/events", json={"events": [event]})
        assert response.status_code == 422, fields


async def test_implicit_variant(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    ids = variant_ids(experiment)
    subjects = [f"user-{i}" for i in range(20)]
    result = await _post(client, [_event(experiment, s, name="conversion") for s in subjects])
    assert result == {"accepted": 20, "duplicates": 0, "skipped": 0}
    stored = {e.subject_id: e.variant_id for e in await stored_events(app, experiment["id"])}
    for subject in subjects:
        assigned = (
            await client.post(
                f"/v1/experiments/{experiment['id']}/assign", json={"subject_id": subject}
            )
        ).json()
        assert stored[subject] == ids[assigned["variant"]["key"]]
    assert len(set(stored.values())) == 2  # both variants used


async def test_explicit_variant_is_trusted(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, traffic_percent=1, salt="fixed")
    outsider = next(f"u{i}" for i in range(1000) if not assignment.is_enrolled("fixed", 1, f"u{i}"))
    result = await _post(
        client,
        [
            _event(experiment, outsider, name="exposure", variant="control"),
            _event(experiment, outsider, name="conversion"),  # not enrolled -> skipped
        ],
    )
    assert result == {"accepted": 1, "duplicates": 0, "skipped": 1}


async def test_draft_experiment_events_skipped(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    draft = await create_experiment(client)
    events = [
        _event(draft, "alice", name="exposure"),
        _event(draft, "bob", name="conversion", variant="treatment"),
    ]
    assert await _post(client, events) == {"accepted": 0, "duplicates": 0, "skipped": 2}
    assert await stored_events(app, draft["id"]) == []


async def test_paused_accepts_completed_skips(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await transition(client, experiment["id"], "pause")
    assert (await _post(client, [_event(experiment, "a", name="conversion")]))["accepted"] == 1
    await transition(client, experiment["id"], "complete")
    assert (await _post(client, [_event(experiment, "b", name="conversion")]))["skipped"] == 1


async def test_mixed_experiments_in_one_batch(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    running = await running_experiment(client)
    draft = await create_experiment(client, prompt="other")
    result = await _post(
        client,
        [
            _event(running, "a", name="exposure", event_id="e1"),
            _event(draft, "a", name="exposure", event_id="e1"),
            _event(running, "b", name="exposure", event_id="e2"),
        ],
    )
    assert result == {"accepted": 2, "duplicates": 0, "skipped": 1}


async def test_retried_batch(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    events = [_event(experiment, f"s{i}", name="exposure", event_id=f"evt-{i}") for i in range(5)]
    assert await _post(client, events) == {"accepted": 5, "duplicates": 0, "skipped": 0}
    assert await _post(client, events) == {"accepted": 0, "duplicates": 5, "skipped": 0}
    assert len(await stored_events(app, experiment["id"])) == 5


async def test_event_ids_are_scoped_per_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    first = await running_experiment(client)
    second = await running_experiment(client, prompt="other")
    await _post(client, [_event(first, "a", name="exposure", event_id="same")])
    result = await _post(client, [_event(second, "a", name="exposure", event_id="same")])
    assert result["accepted"] == 1


async def test_duplicates_within_batch(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    events = [
        _event(experiment, "a", name="exposure", event_id="x"),
        _event(experiment, "a", name="exposure", event_id="x"),
        _event(experiment, "a", name="conversion"),
        _event(experiment, "a", name="conversion"),  # no event_id: never deduplicated
    ]
    assert await _post(client, events) == {"accepted": 3, "duplicates": 1, "skipped": 0}


async def test_timestamp_is_stored(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await _post(
        client,
        [
            _event(experiment, "a", name="exposure", timestamp="2026-01-02T03:04:05Z"),
            _event(experiment, "b", name="exposure"),
        ],
    )
    first, second = await stored_events(app, experiment["id"])
    assert first.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert (datetime.now(UTC) - second.created_at).total_seconds() < 60


async def test_concurrent_duplicate_is_detected(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent insert between the pre-select and the insert trips the unique constraint."""
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await _post(client, [_event(experiment, "a", name="exposure", event_id="raced")])

    real = analytics.existing_event_ids
    calls = 0

    async def stale_first_lookup(
        session: AsyncSession, keys: Collection[tuple[uuid.UUID, str]]
    ) -> set[tuple[uuid.UUID, str]]:
        nonlocal calls
        calls += 1
        return set() if calls == 1 else await real(session, keys)

    monkeypatch.setattr(analytics, "existing_event_ids", stale_first_lookup)
    result = await _post(
        client,
        [
            _event(experiment, "a", name="exposure", event_id="raced"),
            _event(experiment, "b", name="exposure", event_id="fresh"),
        ],
    )
    assert result == {"accepted": 1, "duplicates": 1, "skipped": 0}
    assert calls == 2
    assert len(await stored_events(app, experiment["id"])) == 2


async def test_persistent_race_gives_up(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await _post(client, [_event(experiment, "a", name="exposure", event_id="raced")])

    async def always_stale(
        session: AsyncSession, keys: Collection[tuple[uuid.UUID, str]]
    ) -> set[tuple[uuid.UUID, str]]:
        return set()

    monkeypatch.setattr(analytics, "existing_event_ids", always_stale)
    response = await client.post(
        "/v1/events",
        json={"events": [_event(experiment, "a", name="exposure", event_id="raced")]},
    )
    assert response.status_code == 409
    assert len(await stored_events(app, experiment["id"])) == 1
