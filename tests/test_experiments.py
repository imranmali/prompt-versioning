"""Experiment definition, validation, listing and lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from promptlab.models import LabelEvent
from tests.experiment_factories import (
    create_experiment,
    experiment_payload,
    label_version,
    running_experiment,
    seed_prompt,
    transition,
    variants,
)

# ---------------------------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------------------------


async def test_experiment_created(app: FastAPI, editor_client: AsyncClient) -> None:
    await seed_prompt(app)
    response = await editor_client.post(
        "/v1/experiments",
        json=experiment_payload(
            description="v2 greeting",
            variants=variants(("control", 1, 50), ("treatment", 2, 50)),
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["prompt"] == "greet"
    assert body["name"] == "greeting-test"
    assert body["description"] == "v2 greeting"
    assert body["traffic_percent"] == 100
    assert body["primary_metric"] == "conversion"
    assert body["fallback_label"] == "production"
    assert len(body["salt"]) == 16
    assert body["winner"] is None
    assert body["started_at"] is None
    assert body["ended_at"] is None
    assert [(v["key"], v["version"], v["weight"], v["is_control"]) for v in body["variants"]] == [
        ("control", 1, 50, True),
        ("treatment", 2, 50, False),
    ]
    assert all(uuid.UUID(v["id"]) for v in body["variants"])


async def test_create_with_all_options(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    body = await create_experiment(
        client,
        traffic_percent=25,
        primary_metric="checkout.completed",
        fallback_label="stable",
        salt="my-salt",
        variants=[{"key": "a", "version": 1}, {"key": "b", "version": 3}],
    )
    assert body["traffic_percent"] == 25
    assert body["primary_metric"] == "checkout.completed"
    assert body["fallback_label"] == "stable"
    assert body["salt"] == "my-salt"
    assert [v["weight"] for v in body["variants"]] == [1, 1]


async def test_random_salt_per_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    first = await create_experiment(client, name="one")
    second = await create_experiment(client, name="two")
    assert first["salt"] != second["salt"]


async def test_too_few_variants(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    response = await client.post(
        "/v1/experiments", json=experiment_payload(variants=variants(("only", 1, 1)))
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_too_many_variants(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    eleven = [{"key": f"v{i}", "version": 1} for i in range(11)]
    response = await client.post("/v1/experiments", json=experiment_payload(variants=eleven))
    assert response.status_code == 422


async def test_variant_references_unknown_version(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    response = await client.post(
        "/v1/experiments",
        json=experiment_payload(variants=variants(("control", 1, 1), ("treatment", 9, 1))),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"unknown_versions": [9]}


async def test_unknown_prompt(client: AsyncClient) -> None:
    response = await client.post("/v1/experiments", json=experiment_payload("nope"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_implicit_control(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    body = await create_experiment(
        client, variants=variants(("first", 2, 1), ("second", 1, 1), ("third", 3, 1))
    )
    assert [v["is_control"] for v in body["variants"]] == [True, False, False]


async def test_explicit_control(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    body = await create_experiment(
        client, variants=variants(("new", 2, 1), ("baseline", 1, 1), control="baseline")
    )
    assert [(v["key"], v["is_control"]) for v in body["variants"]] == [
        ("new", False),
        ("baseline", True),
    ]


async def test_multiple_controls_rejected(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    payload = experiment_payload(
        variants=[
            {"key": "a", "version": 1, "is_control": True},
            {"key": "b", "version": 2, "is_control": True},
        ]
    )
    response = await client.post("/v1/experiments", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"controls": ["a", "b"]}


async def test_duplicate_variant_keys_rejected(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    payload = experiment_payload(variants=variants(("a", 1, 1), ("a", 2, 1)))
    response = await client.post("/v1/experiments", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"duplicate_keys": ["a"]}


async def test_field_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    invalid = [
        {"traffic_percent": 0},
        {"traffic_percent": 101},
        {"primary_metric": "exposure"},
        {"primary_metric": "Has Spaces"},
        {"fallback_label": "Prod!"},
        {"name": ""},
        {"variants": [{"key": "A", "version": 1}, {"key": "b", "version": 2}]},
        {"variants": [{"key": "a", "version": 1, "weight": 0}, {"key": "b", "version": 2}]},
        {"unknown_field": True},
    ]
    for overrides in invalid:
        response = await client.post("/v1/experiments", json=experiment_payload(**overrides))
        assert response.status_code == 422, overrides


async def test_duplicate_name_per_prompt(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    await create_experiment(client)
    response = await client.post("/v1/experiments", json=experiment_payload())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    # The same name on another prompt is fine.
    await create_experiment(client, prompt="other")


async def test_runtime_role_cannot_manage(
    app: FastAPI, client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await seed_prompt(app)
    experiment = await create_experiment(client)
    assert (
        await runtime_client.post("/v1/experiments", json=experiment_payload(name="x"))
    ).status_code == 403
    url = f"/v1/experiments/{experiment['id']}"
    assert (await runtime_client.patch(url, json={"description": "x"})).status_code == 403
    for action in ("start", "pause", "complete"):
        assert (await runtime_client.post(f"{url}/{action}")).status_code == 403
    assert (await runtime_client.get(url)).status_code == 200
    assert (await runtime_client.get("/v1/experiments")).status_code == 200


# ---------------------------------------------------------------------------------------------
# List and get
# ---------------------------------------------------------------------------------------------


async def test_filter_by_status(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    running = await running_experiment(client, name="live")
    await create_experiment(client, name="draft")
    await running_experiment(client, prompt="other", name="live-too")
    response = await client.get("/v1/experiments", params={"status": "running"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {i["status"] for i in body["items"]} == {"running"}
    assert running["id"] in {i["id"] for i in body["items"]}


async def test_filter_by_prompt_and_paginate(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    for i in range(3):
        await create_experiment(client, name=f"exp-{i}")
    await create_experiment(client, prompt="other")

    body = (await client.get("/v1/experiments", params={"prompt": "greet", "limit": 2})).json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert {i["prompt"] for i in body["items"]} == {"greet"}
    rest = (
        await client.get("/v1/experiments", params={"prompt": "greet", "limit": 2, "offset": 2})
    ).json()
    assert len(rest["items"]) == 1
    names = {i["name"] for i in body["items"]} | {i["name"] for i in rest["items"]}
    assert names == {"exp-0", "exp-1", "exp-2"}

    everything = (await client.get("/v1/experiments")).json()
    assert everything["total"] == 4
    created = [datetime.fromisoformat(i["created_at"]) for i in everything["items"]]
    assert created == sorted(created, reverse=True)  # newest first
    assert (await client.get("/v1/experiments", params={"prompt": "zzz"})).json()["total"] == 0
    assert (await client.get("/v1/experiments", params={"status": "bogus"})).status_code == 422


async def test_get_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    created = await create_experiment(client)
    response = await client.get(f"/v1/experiments/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created
    missing = await client.get(f"/v1/experiments/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert (await client.get("/v1/experiments/not-a-uuid")).status_code == 422


# ---------------------------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------------------------


async def test_edit_draft_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    created = await create_experiment(client)
    response = await client.patch(
        f"/v1/experiments/{created['id']}",
        json={
            "description": "updated",
            "traffic_percent": 30,
            "primary_metric": "signup",
            "fallback_label": "staging",
            # Re-use the "control" key with a different version and add a third variant.
            "variants": variants(("control", 2, 2), ("treatment", 3, 1), ("extra", 1, 1)),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == "updated"
    assert body["traffic_percent"] == 30
    assert body["primary_metric"] == "signup"
    assert body["fallback_label"] == "staging"
    assert [(v["key"], v["version"], v["weight"], v["is_control"]) for v in body["variants"]] == [
        ("control", 2, 2, True),
        ("treatment", 3, 1, False),
        ("extra", 1, 1, False),
    ]
    assert body["salt"] == created["salt"]
    # Persisted.
    assert (await client.get(f"/v1/experiments/{created['id']}")).json() == body


async def test_patch_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    created = await create_experiment(client)
    url = f"/v1/experiments/{created['id']}"
    bad_version = await client.patch(url, json={"variants": variants(("a", 1, 1), ("b", 7, 1))})
    assert bad_version.status_code == 422
    assert (await client.patch(url, json={"primary_metric": "exposure"})).status_code == 422
    assert (await client.patch(url, json={"variants": variants(("a", 1, 1))})).status_code == 422
    assert (await client.patch(url, json={"status": "running"})).status_code == 422
    missing = await client.patch(f"/v1/experiments/{uuid.uuid4()}", json={"description": "x"})
    assert missing.status_code == 404
    # Nothing changed.
    assert (await client.get(url)).json()["variants"] == created["variants"]


async def test_edit_running_experiment_variants(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    url = f"/v1/experiments/{experiment['id']}"
    response = await client.patch(url, json={"variants": variants(("a", 1, 1), ("b", 3, 1))})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
    for change in ({"traffic_percent": 10}, {"primary_metric": "x"}, {"fallback_label": "y"}):
        assert (await client.patch(url, json=change)).status_code == 409
    # The description can still change while running or paused.
    described = await client.patch(url, json={"description": "now running"})
    assert described.status_code == 200
    assert described.json()["description"] == "now running"
    await transition(client, experiment["id"], "pause")
    paused = await client.patch(url, json={"description": "paused"})
    assert paused.status_code == 200
    assert (await client.patch(url, json={"traffic_percent": 50})).status_code == 409


async def test_completed_experiment_rejects_all_patches(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await transition(client, experiment["id"], "complete")
    response = await client.patch(
        f"/v1/experiments/{experiment['id']}", json={"description": "late"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"


# ---------------------------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------------------------


async def test_start_experiment(app: FastAPI, editor_client: AsyncClient) -> None:
    await seed_prompt(app)
    created = await create_experiment(editor_client)
    body = await transition(editor_client, created["id"], "start")
    assert body["status"] == "running"
    assert body["started_at"] is not None
    assert body["ended_at"] is None


async def test_pause_and_resume_keeps_started_at(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    started = await running_experiment(client)
    paused = await transition(client, started["id"], "pause")
    assert paused["status"] == "paused"
    resumed = await transition(client, started["id"], "start")
    assert resumed["status"] == "running"
    assert resumed["started_at"] == started["started_at"]


async def test_second_running_experiment_rejected(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    await seed_prompt(app, name="other")
    first = await running_experiment(client, name="first")
    second = await create_experiment(client, name="second")
    response = await client.post(f"/v1/experiments/{second['id']}/start")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert response.json()["error"]["details"] == {"running_experiment": "first"}
    # Experiments on other prompts are unaffected.
    await running_experiment(client, prompt="other", name="elsewhere")
    # Once the first one is paused the second can start.
    await transition(client, first["id"], "pause")
    assert (await transition(client, second["id"], "start"))["status"] == "running"
    # ... and the paused one cannot resume while the second runs.
    assert (await client.post(f"/v1/experiments/{first['id']}/start")).status_code == 409


async def test_restart_completed_experiment(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await transition(client, experiment["id"], "complete")
    response = await client.post(f"/v1/experiments/{experiment['id']}/start")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "invalid_state"
    assert error["details"] == {"status": "completed", "allowed": ["draft", "paused"]}


async def test_invalid_transitions(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    draft = await create_experiment(client)
    url = f"/v1/experiments/{draft['id']}"
    for action in ("pause", "complete"):
        response = await client.post(f"{url}/{action}")
        assert response.status_code == 409, action
        assert response.json()["error"]["code"] == "invalid_state"
    await transition(client, draft["id"], "start")
    assert (await client.post(f"{url}/start")).status_code == 409
    await transition(client, draft["id"], "pause")
    assert (await client.post(f"{url}/pause")).status_code == 409
    completed = await transition(client, draft["id"], "complete")  # paused -> completed
    assert completed["status"] == "completed"
    for action in ("start", "pause", "complete"):
        assert (await client.post(f"{url}/{action}")).status_code == 409
    missing = f"/v1/experiments/{uuid.uuid4()}"
    for action in ("start", "pause", "complete"):
        assert (await client.post(f"{missing}/{action}")).status_code == 404


async def test_complete_without_winner(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    response = await client.post(f"/v1/experiments/{experiment['id']}/complete", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["winner"] is None
    assert body["ended_at"] is not None
    assert await label_version(app, "greet", "production") == 1


async def test_promote_winner_to_production(app: FastAPI, editor_client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(editor_client)
    response = await editor_client.post(
        f"/v1/experiments/{experiment['id']}/complete",
        json={"winner": "treatment", "promote_label": "production"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["winner"] == "treatment"
    assert body["ended_at"] is not None
    assert await label_version(app, "greet", "production") == 2
    async with app.state.session_factory() as session:
        history = (
            await session.scalars(
                select(LabelEvent).where(LabelEvent.label == "production").order_by(LabelEvent.id)
            )
        ).all()
    assert [(e.from_version, e.to_version, e.actor) for e in history][-1] == (1, 2, "editor-key")


async def test_promote_creates_new_label(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await transition(client, experiment["id"], "pause")
    response = await client.post(
        f"/v1/experiments/{experiment['id']}/complete",
        json={"winner": "control", "promote_label": "winner"},
    )
    assert response.status_code == 200
    assert response.json()["winner"] == "control"
    assert await label_version(app, "greet", "winner") == 1


async def test_complete_winner_without_promotion(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    body = (
        await client.post(
            f"/v1/experiments/{experiment['id']}/complete", json={"winner": "treatment"}
        )
    ).json()
    assert body["winner"] == "treatment"
    assert await label_version(app, "greet", "production") == 1


async def test_complete_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    url = f"/v1/experiments/{experiment['id']}/complete"
    no_winner = await client.post(url, json={"promote_label": "production"})
    assert no_winner.status_code == 422
    unknown = await client.post(url, json={"winner": "ghost", "promote_label": "production"})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["details"] == {"variants": ["control", "treatment"]}
    # Nothing changed.
    current = (await client.get(f"/v1/experiments/{experiment['id']}")).json()
    assert current["status"] == "running"
    assert await label_version(app, "greet", "production") == 1
