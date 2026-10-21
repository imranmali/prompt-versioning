"""Deployment labels: assign, list, delete, history and rollback."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

BASE = "/v1/prompts/support-reply"


@pytest.fixture
async def prompt(editor_client: AsyncClient) -> str:
    """A prompt with versions 1..3."""
    assert (
        await editor_client.post("/v1/prompts", json={"name": "support-reply"})
    ).status_code == 201
    for i in range(1, 4):
        response = await editor_client.post(f"{BASE}/versions", json={"template": f"v{i}"})
        assert response.status_code == 201
    return "support-reply"


async def _put(client: AsyncClient, label: str, version: int) -> dict[str, Any]:
    response = await client.put(f"{BASE}/labels/{label}", json={"version": version})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _history(client: AsyncClient, label: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{BASE}/labels/{label}/history", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _moves(history: dict[str, Any]) -> list[tuple[int | None, int | None]]:
    return [(e["from_version"], e["to_version"]) for e in history["items"]]


# --- Assign --------------------------------------------------------------------------------


@pytest.mark.usefixtures("prompt")
async def test_promote_to_production(editor_client: AsyncClient) -> None:
    body = await _put(editor_client, "production", 2)
    assert body["name"] == "production"
    assert body["version"] == 2
    assert body["updated_by"] == "editor-key"
    assert set(body) == {"name", "version", "updated_by", "updated_at"}

    prompt = (await editor_client.get(BASE)).json()
    assert prompt["labels"] == {"production": 2}

    history = await _history(editor_client, "production")
    assert history["total"] == 1
    entry = history["items"][0]
    assert entry["label"] == "production"
    assert (entry["from_version"], entry["to_version"]) == (None, 2)
    assert entry["actor"] == "editor-key"
    assert set(entry) == {"label", "from_version", "to_version", "actor", "created_at"}


@pytest.mark.usefixtures("prompt")
async def test_label_unknown_version(editor_client: AsyncClient) -> None:
    response = await editor_client.put(f"{BASE}/labels/production", json={"version": 42})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert (await editor_client.get(f"{BASE}/labels")).json() == []
    assert (await _history(editor_client, "production"))["total"] == 0


@pytest.mark.usefixtures("prompt")
async def test_move_label_records_previous_version(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    body = await _put(editor_client, "production", 3)
    assert body["version"] == 3
    assert _moves(await _history(editor_client, "production")) == [(1, 3), (None, 1)]


@pytest.mark.usefixtures("prompt")
async def test_putting_same_version_records_no_history(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    assert (await _put(editor_client, "production", 1))["version"] == 1
    assert (await _history(editor_client, "production"))["total"] == 1


@pytest.mark.usefixtures("prompt")
@pytest.mark.parametrize("label", ["Production", "-prod", "prod.v1", "a" * 65, "with space"])
async def test_invalid_label_name(editor_client: AsyncClient, label: str) -> None:
    response = await editor_client.put(f"{BASE}/labels/{label}", json={"version": 1})
    assert response.status_code == 422


@pytest.mark.usefixtures("prompt")
@pytest.mark.parametrize("label", ["prod", "0", "canary_eu-west", "a" * 64])
async def test_valid_label_names(editor_client: AsyncClient, label: str) -> None:
    assert (await _put(editor_client, label, 1))["name"] == label


@pytest.mark.usefixtures("prompt")
@pytest.mark.parametrize(
    "payload", [{}, {"version": "two"}, {"version": 0}, {"version": 1, "x": 1}]
)
async def test_invalid_label_payload(editor_client: AsyncClient, payload: dict[str, Any]) -> None:
    response = await editor_client.put(f"{BASE}/labels/production", json=payload)
    assert response.status_code == 422


async def test_label_on_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.put("/v1/prompts/missing/labels/production", json={"version": 1})
    assert response.status_code == 404


@pytest.mark.usefixtures("prompt")
async def test_runtime_key_cannot_modify_labels(
    editor_client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await _put(editor_client, "production", 2)
    put = await runtime_client.put(f"{BASE}/labels/production", json={"version": 1})
    assert put.status_code == 403
    assert (await runtime_client.delete(f"{BASE}/labels/production")).status_code == 403
    assert (await runtime_client.post(f"{BASE}/labels/production/rollback")).status_code == 403
    # Runtime keys can read labels and history.
    assert (await runtime_client.get(f"{BASE}/labels")).status_code == 200
    assert (await runtime_client.get(f"{BASE}/labels/production/history")).status_code == 200


# --- List and delete -----------------------------------------------------------------------


@pytest.mark.usefixtures("prompt")
async def test_list_labels(editor_client: AsyncClient) -> None:
    await _put(editor_client, "staging", 3)
    await _put(editor_client, "production", 2)
    response = await editor_client.get(f"{BASE}/labels")
    assert response.status_code == 200
    assert [(item["name"], item["version"]) for item in response.json()] == [
        ("production", 2),
        ("staging", 3),
    ]


async def test_list_labels_unknown_prompt(editor_client: AsyncClient) -> None:
    assert (await editor_client.get("/v1/prompts/missing/labels")).status_code == 404


@pytest.mark.usefixtures("prompt")
async def test_delete_label(editor_client: AsyncClient) -> None:
    await _put(editor_client, "staging", 3)
    await _put(editor_client, "production", 2)

    response = await editor_client.delete(f"{BASE}/labels/staging")
    assert response.status_code == 204
    assert response.content == b""

    labels = (await editor_client.get(f"{BASE}/labels")).json()
    assert [item["name"] for item in labels] == ["production"]
    assert (await editor_client.get(BASE)).json()["labels"] == {"production": 2}

    history = await _history(editor_client, "staging")
    assert _moves(history) == [(3, None), (None, 3)]
    assert history["items"][0]["actor"] == "editor-key"


@pytest.mark.usefixtures("prompt")
async def test_delete_missing_label(editor_client: AsyncClient) -> None:
    response = await editor_client.delete(f"{BASE}/labels/staging")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert (await editor_client.delete("/v1/prompts/missing/labels/staging")).status_code == 404


@pytest.mark.usefixtures("prompt")
async def test_label_can_be_recreated_after_delete(editor_client: AsyncClient) -> None:
    await _put(editor_client, "staging", 1)
    await editor_client.delete(f"{BASE}/labels/staging")
    assert (await _put(editor_client, "staging", 2))["version"] == 2
    assert _moves(await _history(editor_client, "staging")) == [(None, 2), (1, None), (None, 1)]


# --- History -------------------------------------------------------------------------------


@pytest.mark.usefixtures("prompt")
async def test_history_after_two_moves(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    await _put(editor_client, "production", 2)
    await _put(editor_client, "staging", 3)  # other labels do not leak into the history
    history = await _history(editor_client, "production")
    assert _moves(history) == [(1, 2), (None, 1)]
    assert history["total"] == 2
    assert {e["label"] for e in history["items"]} == {"production"}


@pytest.mark.usefixtures("prompt")
async def test_history_pagination(editor_client: AsyncClient) -> None:
    for version in (1, 2, 3, 1):
        await _put(editor_client, "production", version)
    page = await _history(editor_client, "production", limit=2, offset=1)
    assert page["total"] == 4
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert _moves(page) == [(2, 3), (1, 2)]


@pytest.mark.usefixtures("prompt")
async def test_history_of_unknown_label_is_empty(editor_client: AsyncClient) -> None:
    assert await _history(editor_client, "never") == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }


async def test_history_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.get("/v1/prompts/missing/labels/production/history")
    assert response.status_code == 404


# --- Rollback ------------------------------------------------------------------------------


@pytest.mark.usefixtures("prompt")
async def test_rollback_production(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    await _put(editor_client, "production", 2)

    response = await editor_client.post(f"{BASE}/labels/production/rollback")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "production"
    assert body["version"] == 1
    assert body["updated_by"] == "editor-key"

    assert (await editor_client.get(BASE)).json()["labels"] == {"production": 1}
    history = await _history(editor_client, "production")
    assert _moves(history) == [(2, 1), (1, 2), (None, 1)]
    assert history["items"][0]["actor"] == "editor-key"


@pytest.mark.usefixtures("prompt")
async def test_repeated_rollbacks_toggle(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    await _put(editor_client, "production", 3)
    url = f"{BASE}/labels/production/rollback"
    assert (await editor_client.post(url)).json()["version"] == 1
    assert (await editor_client.post(url)).json()["version"] == 3


@pytest.mark.usefixtures("prompt")
async def test_nothing_to_roll_back_to(editor_client: AsyncClient) -> None:
    await _put(editor_client, "production", 1)
    response = await editor_client.post(f"{BASE}/labels/production/rollback")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert (await editor_client.get(BASE)).json()["labels"] == {"production": 1}
    assert (await _history(editor_client, "production"))["total"] == 1


@pytest.mark.usefixtures("prompt")
async def test_rollback_missing_or_deleted_label(editor_client: AsyncClient) -> None:
    response = await editor_client.post(f"{BASE}/labels/never/rollback")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"

    await _put(editor_client, "staging", 1)
    await _put(editor_client, "staging", 2)
    await editor_client.delete(f"{BASE}/labels/staging")
    assert (await editor_client.post(f"{BASE}/labels/staging/rollback")).status_code == 409


@pytest.mark.usefixtures("prompt")
async def test_rollback_after_recreate_has_nothing_to_roll_back(
    editor_client: AsyncClient,
) -> None:
    await _put(editor_client, "staging", 1)
    await editor_client.delete(f"{BASE}/labels/staging")
    await _put(editor_client, "staging", 2)
    assert (await editor_client.post(f"{BASE}/labels/staging/rollback")).status_code == 409


async def test_rollback_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.post("/v1/prompts/missing/labels/production/rollback")
    assert response.status_code == 404
