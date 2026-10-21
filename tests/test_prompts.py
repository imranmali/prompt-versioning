"""Prompt registry: create, list/search/filter, fetch and update prompts."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from promptlab.services import prompts as prompt_service


async def _create(client: AsyncClient, name: str, **fields: Any) -> dict[str, Any]:
    response = await client.post("/v1/prompts", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _add_version(client: AsyncClient, name: str, template: str) -> dict[str, Any]:
    response = await client.post(f"/v1/prompts/{name}/versions", json={"template": template})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Create --------------------------------------------------------------------------------


async def test_prompt_created(editor_client: AsyncClient) -> None:
    response = await editor_client.post(
        "/v1/prompts", json={"name": "support-reply", "tags": ["support"]}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "support-reply"
    assert body["tags"] == ["support"]
    assert body["description"] == ""
    assert body["latest_version"] is None
    assert body["labels"] == {}
    assert set(body) == {
        "id",
        "name",
        "description",
        "tags",
        "latest_version",
        "labels",
        "created_at",
        "updated_at",
    }


async def test_duplicate_name_rejected(editor_client: AsyncClient) -> None:
    await _create(editor_client, "support-reply")
    response = await editor_client.post("/v1/prompts", json={"name": "support-reply"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_duplicate_name_race_maps_integrity_error_to_conflict(
    editor_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create(editor_client, "support-reply")

    async def never_taken(*_: object) -> bool:
        return False

    # Simulate losing the race: the pre-check passes but the unique constraint fires.
    monkeypatch.setattr(prompt_service, "_name_taken", never_taken)
    response = await editor_client.post("/v1/prompts", json={"name": "support-reply"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "name", ["Bad Name!", "", "-leading-dash", "UPPER", "a" * 129, "has/slash", ".dot"]
)
async def test_invalid_name_rejected(editor_client: AsyncClient, name: str) -> None:
    response = await editor_client.post("/v1/prompts", json={"name": name})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("name", ["a", "0", "support.reply_v2-final", "a" * 128])
async def test_valid_names_accepted(editor_client: AsyncClient, name: str) -> None:
    await _create(editor_client, name)


async def test_tags_deduplicated_preserving_order(editor_client: AsyncClient) -> None:
    body = await _create(editor_client, "p", tags=["b", "a", "b", "c", "a"])
    assert body["tags"] == ["b", "a", "c"]


@pytest.mark.parametrize(
    "tags",
    [[""], ["x" * 65], [f"t{i}" for i in range(33)], "support", [1]],
)
async def test_invalid_tags_rejected(editor_client: AsyncClient, tags: object) -> None:
    response = await editor_client.post("/v1/prompts", json={"name": "p", "tags": tags})
    assert response.status_code == 422


async def test_unknown_fields_rejected(editor_client: AsyncClient) -> None:
    response = await editor_client.post("/v1/prompts", json={"name": "p", "owner": "me"})
    assert response.status_code == 422


async def test_runtime_key_cannot_create(runtime_client: AsyncClient) -> None:
    response = await runtime_client.post("/v1/prompts", json={"name": "p"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_anonymous_rejected(anon_client: AsyncClient) -> None:
    assert (await anon_client.get("/v1/prompts")).status_code == 401
    assert (await anon_client.post("/v1/prompts", json={"name": "p"})).status_code == 401


# --- List and fetch ------------------------------------------------------------------------


async def test_paginated_listing(editor_client: AsyncClient, runtime_client: AsyncClient) -> None:
    for name in ("charlie", "alpha", "bravo"):
        await _create(editor_client, name)
    response = await runtime_client.get("/v1/prompts", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [p["name"] for p in body["items"]] == ["alpha", "bravo"]

    body = (await runtime_client.get("/v1/prompts", params={"limit": 2, "offset": 2})).json()
    assert body["total"] == 3
    assert [p["name"] for p in body["items"]] == ["charlie"]


async def test_listing_pagination_params_validated(client: AsyncClient) -> None:
    assert (await client.get("/v1/prompts", params={"limit": 0})).status_code == 422
    assert (await client.get("/v1/prompts", params={"limit": 201})).status_code == 422
    assert (await client.get("/v1/prompts", params={"offset": -1})).status_code == 422


async def test_filter_by_tag(editor_client: AsyncClient) -> None:
    await _create(editor_client, "a-support", tags=["support", "email"])
    await _create(editor_client, "b-sales", tags=["sales"])
    await _create(editor_client, "c-support", tags=["support"])
    await _create(editor_client, "d-supportish", tags=["supporting", "x-support"])
    await _create(editor_client, "e-untagged")

    body = (await editor_client.get("/v1/prompts", params={"tag": "support"})).json()
    assert [p["name"] for p in body["items"]] == ["a-support", "c-support"]
    assert body["total"] == 2

    body = (await editor_client.get("/v1/prompts", params={"tag": "support", "limit": 1})).json()
    assert [p["name"] for p in body["items"]] == ["a-support"]
    assert body["total"] == 2

    body = (await editor_client.get("/v1/prompts", params={"tag": "missing"})).json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_filter_by_tag_with_special_characters(editor_client: AsyncClient) -> None:
    await _create(editor_client, "quoted", tags=['say "hi"', "50%", "é"])
    await _create(editor_client, "other", tags=["say hi", "50"])
    for tag in ('say "hi"', "50%", "é"):
        body = (await editor_client.get("/v1/prompts", params={"tag": tag})).json()
        assert [p["name"] for p in body["items"]] == ["quoted"], tag
        assert body["total"] == 1


async def test_search_is_case_insensitive_on_name_and_description(
    editor_client: AsyncClient,
) -> None:
    await _create(editor_client, "support-reply")
    await _create(editor_client, "greeting", description="Friendly SUPPORT greeting")
    await _create(editor_client, "billing", description="Invoices")

    body = (await editor_client.get("/v1/prompts", params={"search": "Support"})).json()
    assert [p["name"] for p in body["items"]] == ["greeting", "support-reply"]
    assert body["total"] == 2

    body = (
        await editor_client.get("/v1/prompts", params={"search": "support", "tag": "none"})
    ).json()
    assert body["total"] == 0


async def test_search_escapes_like_wildcards(editor_client: AsyncClient) -> None:
    await _create(editor_client, "discount", description="Take 100% off")
    await _create(editor_client, "plain", description="Take 1000 off")
    body = (await editor_client.get("/v1/prompts", params={"search": "0%"})).json()
    assert [p["name"] for p in body["items"]] == ["discount"]
    body = (await editor_client.get("/v1/prompts", params={"search": "_"})).json()
    assert body["total"] == 0


async def test_fetch_prompt_includes_latest_version_and_labels(
    editor_client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await _create(editor_client, "greet", description="Says hi", tags=["demo"])
    await _add_version(editor_client, "greet", "Hi {{ name }}")
    await _add_version(editor_client, "greet", "Hello {{ name }}")
    await editor_client.put("/v1/prompts/greet/labels/production", json={"version": 1})
    await editor_client.put("/v1/prompts/greet/labels/staging", json={"version": 2})

    response = await runtime_client.get("/v1/prompts/greet")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_version"] == 2
    assert body["labels"] == {"production": 1, "staging": 2}
    assert body["description"] == "Says hi"
    assert body["tags"] == ["demo"]

    listing = (await runtime_client.get("/v1/prompts")).json()
    assert listing["items"][0]["latest_version"] == 2
    assert listing["items"][0]["labels"] == {"production": 1, "staging": 2}


async def test_listing_summaries_are_per_prompt(editor_client: AsyncClient) -> None:
    await _create(editor_client, "one")
    await _create(editor_client, "two")
    await _add_version(editor_client, "two", "x")
    await editor_client.put("/v1/prompts/two/labels/production", json={"version": 1})
    items = (await editor_client.get("/v1/prompts")).json()["items"]
    assert [(p["name"], p["latest_version"], p["labels"]) for p in items] == [
        ("one", None, {}),
        ("two", 1, {"production": 1}),
    ]


async def test_unknown_prompt(runtime_client: AsyncClient) -> None:
    response = await runtime_client.get("/v1/prompts/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- Update --------------------------------------------------------------------------------


async def test_update_tags(editor_client: AsyncClient) -> None:
    created = await _create(editor_client, "greet", description="d", tags=["x"])
    await _add_version(editor_client, "greet", "Hi {{ name }}")
    versions_before = (await editor_client.get("/v1/prompts/greet/versions")).json()

    response = await editor_client.patch("/v1/prompts/greet", json={"tags": ["a", "b"]})
    assert response.status_code == 200
    body = response.json()
    assert body["tags"] == ["a", "b"]
    assert body["name"] == "greet"
    assert body["description"] == "d"
    assert body["id"] == created["id"]
    assert body["latest_version"] == 1
    assert body["updated_at"] >= created["updated_at"]

    assert (await editor_client.get("/v1/prompts/greet")).json()["tags"] == ["a", "b"]
    versions_after = (await editor_client.get("/v1/prompts/greet/versions")).json()
    assert versions_after == versions_before


async def test_update_description_only(editor_client: AsyncClient) -> None:
    await _create(editor_client, "greet", tags=["keep"])
    body = (await editor_client.patch("/v1/prompts/greet", json={"description": "new"})).json()
    assert body["description"] == "new"
    assert body["tags"] == ["keep"]


async def test_update_without_changes_is_noop(editor_client: AsyncClient) -> None:
    created = await _create(editor_client, "greet", tags=["keep"])
    response = await editor_client.patch("/v1/prompts/greet", json={"tags": ["keep"]})
    assert response.status_code == 200
    assert response.json()["updated_at"] == created["updated_at"]


async def test_update_rejects_name_change_and_bad_tags(editor_client: AsyncClient) -> None:
    await _create(editor_client, "greet")
    assert (
        await editor_client.patch("/v1/prompts/greet", json={"name": "other"})
    ).status_code == 422
    assert (await editor_client.patch("/v1/prompts/greet", json={"tags": [""]})).status_code == 422


async def test_update_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.patch("/v1/prompts/missing", json={"description": "x"})
    assert response.status_code == 404


async def test_runtime_key_cannot_update(
    editor_client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await _create(editor_client, "greet")
    response = await runtime_client.patch("/v1/prompts/greet", json={"description": "x"})
    assert response.status_code == 403
