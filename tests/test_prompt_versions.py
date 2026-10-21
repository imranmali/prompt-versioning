"""Immutable prompt versions: creation, idempotency, browsing, concurrency and diffs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from promptlab.errors import ConflictError
from promptlab.models import Prompt, PromptVersion
from promptlab.schemas.prompts import VersionCreate
from promptlab.services import prompts as prompt_service


async def _create(client: AsyncClient, name: str = "support-reply") -> None:
    response = await client.post("/v1/prompts", json={"name": name})
    assert response.status_code == 201, response.text


async def _add_version(
    client: AsyncClient, template: str, name: str = "support-reply", **fields: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/prompts/{name}/versions", json={"template": template, **fields}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Creation ------------------------------------------------------------------------------


async def test_first_version(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    response = await editor_client.post(
        "/v1/prompts/support-reply/versions",
        json={
            "template": "Hello {{ name }}",
            "model_settings": {"model": "gpt-4o", "temperature": 0.2},
            "metadata": {"ticket": "PL-1"},
            "commit_message": "Initial version",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["prompt"] == "support-reply"
    assert body["template"] == "Hello {{ name }}"
    assert body["variables"] == ["name"]
    assert body["model_settings"] == {"model": "gpt-4o", "temperature": 0.2}
    assert body["metadata"] == {"ticket": "PL-1"}
    assert body["commit_message"] == "Initial version"
    assert body["created_by"] == "editor-key"
    assert set(body) == {
        "id",
        "prompt",
        "version",
        "template",
        "variables",
        "model_settings",
        "metadata",
        "commit_message",
        "content_hash",
        "created_by",
        "created_at",
    }


async def test_version_numbers_are_sequential(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    numbers = [(await _add_version(editor_client, f"v{i}"))["version"] for i in range(1, 4)]
    assert numbers == [1, 2, 3]


async def test_versions_numbered_per_prompt(editor_client: AsyncClient) -> None:
    await _create(editor_client, "a")
    await _create(editor_client, "b")
    await _add_version(editor_client, "x", name="a")
    await _add_version(editor_client, "y", name="a")
    assert (await _add_version(editor_client, "x", name="b"))["version"] == 1


async def test_variables_extracted(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    body = await _add_version(editor_client, "Hello {{ name }}, about {{ topic }}")
    assert body["variables"] == ["name", "topic"]
    fetched = (await editor_client.get("/v1/prompts/support-reply/versions/1")).json()
    assert fetched["variables"] == ["name", "topic"]


async def test_invalid_template(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    response = await editor_client.post(
        "/v1/prompts/support-reply/versions", json={"template": "Hello {{ name"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_template"
    assert (await editor_client.get("/v1/prompts/support-reply")).json()["latest_version"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"template": ""},
        {"template": "x" * 100_001},
        {},
        {"template": "x", "model_settings": "fast"},
        {"template": "x", "unknown": 1},
    ],
)
async def test_invalid_version_payload(editor_client: AsyncClient, payload: dict[str, Any]) -> None:
    await _create(editor_client)
    response = await editor_client.post("/v1/prompts/support-reply/versions", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_max_length_template_accepted(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    assert (await _add_version(editor_client, "x" * 100_000))["version"] == 1


async def test_version_for_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.post("/v1/prompts/missing/versions", json={"template": "x"})
    assert response.status_code == 404


async def test_runtime_key_cannot_create_version(
    editor_client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await _create(editor_client)
    response = await runtime_client.post(
        "/v1/prompts/support-reply/versions", json={"template": "x"}
    )
    assert response.status_code == 403


async def test_content_hash_is_canonical_sha256(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    settings = {"temperature": 0.5, "model": "m"}
    body = await _add_version(editor_client, "Hi {{ name }}", model_settings=settings)
    canonical = json.dumps(
        {"template": "Hi {{ name }}", "model_settings": settings},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert body["content_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert body["content_hash"] == prompt_service.content_hash("Hi {{ name }}", settings)


async def test_creating_version_bumps_prompt_updated_at(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    before = (await editor_client.get("/v1/prompts/support-reply")).json()
    await _add_version(editor_client, "x")
    after = (await editor_client.get("/v1/prompts/support-reply")).json()
    assert after["updated_at"] > before["updated_at"]
    assert after["latest_version"] == 1


# --- Idempotency ---------------------------------------------------------------------------


async def test_resubmitting_identical_content(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "v1")
    await _add_version(editor_client, "v2")
    v3 = await _add_version(editor_client, "Hi {{ name }}", model_settings={"a": 1, "b": 2})

    response = await editor_client.post(
        "/v1/prompts/support-reply/versions",
        json={
            "template": "Hi {{ name }}",
            "model_settings": {"b": 2, "a": 1},
            "commit_message": "same content, different message",
            "metadata": {"ignored": True},
        },
    )
    assert response.status_code == 200
    assert response.json() == v3
    assert response.json()["version"] == 3
    versions = (await editor_client.get("/v1/prompts/support-reply/versions")).json()
    assert versions["total"] == 3
    assert (await editor_client.get("/v1/prompts/support-reply/versions/4")).status_code == 404


async def test_resubmit_does_not_bump_updated_at(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "x")
    before = (await editor_client.get("/v1/prompts/support-reply")).json()["updated_at"]
    response = await editor_client.post(
        "/v1/prompts/support-reply/versions", json={"template": "x"}
    )
    assert response.status_code == 200
    after = (await editor_client.get("/v1/prompts/support-reply")).json()["updated_at"]
    assert after == before


async def test_changed_model_settings_create_new_version(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "x", model_settings={"temperature": 0})
    body = await _add_version(editor_client, "x", model_settings={"temperature": 1})
    assert body["version"] == 2


async def test_reverting_to_older_content_creates_new_version(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    first = await _add_version(editor_client, "A")
    await _add_version(editor_client, "B")
    third = await _add_version(editor_client, "A")
    assert third["version"] == 3
    assert third["content_hash"] == first["content_hash"]


# --- Concurrency ---------------------------------------------------------------------------


async def test_concurrent_creations_never_duplicate_numbers(editor_client: AsyncClient) -> None:
    await _create(editor_client)

    async def submit(i: int) -> int:
        response = await editor_client.post(
            "/v1/prompts/support-reply/versions", json={"template": f"template {i}"}
        )
        assert response.status_code == 201, response.text
        number: int = response.json()["version"]
        return number

    numbers = await asyncio.gather(*(submit(i) for i in range(10)))
    assert sorted(numbers) == list(range(1, 11))
    listing = (await editor_client.get("/v1/prompts/support-reply/versions")).json()
    assert [v["version"] for v in listing["items"]] == list(range(10, 0, -1))
    assert sorted(v["template"] for v in listing["items"]) == sorted(
        f"template {i}" for i in range(10)
    )


async def _seed_version(session: AsyncSession) -> None:
    prompt = Prompt(name="greet")
    session.add_all(
        [prompt, PromptVersion(prompt=prompt, version=1, template="Hi", content_hash="x")]
    )
    await session.commit()


async def test_version_conflict_is_retried(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_version(session)
    real_latest = prompt_service._latest_version
    calls = 0

    async def stale_once(s: AsyncSession, prompt: Prompt) -> PromptVersion | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_latest(s, prompt)

    # The first attempt computes version 1 from a stale read and hits the unique constraint.
    monkeypatch.setattr(prompt_service, "_latest_version", stale_once)
    version, created = await prompt_service.create_version(
        session, "greet", VersionCreate(template="Hello"), "alice"
    )
    assert created
    assert version.version == 2
    assert calls == 2


async def test_version_conflict_gives_up_after_bounded_retries(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_version(session)
    calls = 0

    async def always_stale(_s: AsyncSession, _p: Prompt) -> PromptVersion | None:
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(prompt_service, "_latest_version", always_stale)
    with pytest.raises(ConflictError):
        await prompt_service.create_version(
            session, "greet", VersionCreate(template="Hello"), "alice"
        )
    assert calls == prompt_service.MAX_VERSION_ATTEMPTS


# --- Browsing ------------------------------------------------------------------------------


async def test_list_versions_newest_first_with_pagination(
    editor_client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await _create(editor_client)
    for i in range(1, 6):
        await _add_version(editor_client, f"v{i}")
    response = await runtime_client.get(
        "/v1/prompts/support-reply/versions", params={"limit": 2, "offset": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [v["version"] for v in body["items"]] == [4, 3]
    assert all(v["prompt"] == "support-reply" for v in body["items"])


async def test_list_versions_empty_and_unknown(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    body = (await editor_client.get("/v1/prompts/support-reply/versions")).json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert (await editor_client.get("/v1/prompts/missing/versions")).status_code == 404


async def test_fetch_latest_alias(editor_client: AsyncClient, runtime_client: AsyncClient) -> None:
    await _create(editor_client)
    for i in range(1, 4):
        await _add_version(editor_client, f"v{i}")
    response = await runtime_client.get("/v1/prompts/support-reply/versions/latest")
    assert response.status_code == 200
    assert response.json()["version"] == 3
    assert response.json()["template"] == "v3"


async def test_fetch_version_by_number(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    created = await _add_version(editor_client, "Hello {{ who }}")
    await _add_version(editor_client, "v2")
    response = await editor_client.get("/v1/prompts/support-reply/versions/1")
    assert response.status_code == 200
    assert response.json() == created


async def test_unknown_version(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    for i in range(1, 4):
        await _add_version(editor_client, f"v{i}")
    response = await editor_client.get("/v1/prompts/support-reply/versions/99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_latest_of_prompt_without_versions(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    response = await editor_client.get("/v1/prompts/support-reply/versions/latest")
    assert response.status_code == 404
    assert (await editor_client.get("/v1/prompts/missing/versions/1")).status_code == 404


@pytest.mark.parametrize("ref", ["newest", "1.5", "LATEST"])
async def test_invalid_version_reference(editor_client: AsyncClient, ref: str) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "x")
    response = await editor_client.get(f"/v1/prompts/support-reply/versions/{ref}")
    assert response.status_code == 422


async def test_versions_are_immutable(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "x")
    url = "/v1/prompts/support-reply/versions/1"
    assert (await editor_client.put(url, json={"template": "y"})).status_code == 405
    assert (await editor_client.patch(url, json={"template": "y"})).status_code == 405
    assert (await editor_client.delete(url)).status_code == 405
    assert (await editor_client.get(url)).json()["template"] == "x"


# --- Diff ----------------------------------------------------------------------------------


async def test_diff_two_versions(editor_client: AsyncClient, runtime_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "Hi {{ name }}")
    await _add_version(editor_client, "Hello {{ name }} {{ title }}")

    response = await runtime_client.get(
        "/v1/prompts/support-reply/diff", params={"from": 1, "to": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == "support-reply"
    assert body["from_version"] == 1
    assert body["to_version"] == 2
    assert body["template_diff"] == "\n".join(
        [
            "--- v1",
            "+++ v2",
            "@@ -1 +1 @@",
            "-Hi {{ name }}",
            "+Hello {{ name }} {{ title }}",
        ]
    )
    assert body["variables"] == {"added": ["title"], "removed": []}
    assert body["model_settings"] == {"added": {}, "removed": {}, "changed": {}}


async def test_diff_model_settings_and_removed_variables(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(
        editor_client,
        "Line one {{ a }}\nLine two {{ b }}\n",
        model_settings={"model": "m1", "temperature": 0.1, "stop": ["x"]},
    )
    await _add_version(
        editor_client,
        "Line one {{ a }}\nLine 2\n",
        model_settings={"model": "m2", "temperature": 0.1, "max_tokens": 50},
    )
    body = (
        await editor_client.get(
            "/v1/prompts/support-reply/diff", params={"from": "1", "to": "latest"}
        )
    ).json()
    assert body["to_version"] == 2
    assert body["variables"] == {"added": [], "removed": ["b"]}
    assert body["model_settings"] == {
        "added": {"max_tokens": 50},
        "removed": {"stop": ["x"]},
        "changed": {"model": {"from": "m1", "to": "m2"}},
    }
    assert "-Line two {{ b }}" in body["template_diff"].splitlines()
    assert "+Line 2" in body["template_diff"].splitlines()
    assert " Line one {{ a }}" in body["template_diff"].splitlines()


async def test_diff_reverse_and_identical(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "Hi {{ name }}")
    await _add_version(editor_client, "Hello {{ name }} {{ title }}")
    reverse = (
        await editor_client.get(
            "/v1/prompts/support-reply/diff", params={"from": "latest", "to": 1}
        )
    ).json()
    assert reverse["from_version"] == 2
    assert reverse["template_diff"].startswith("--- v2\n+++ v1")
    assert reverse["variables"] == {"added": [], "removed": ["title"]}

    same = (
        await editor_client.get("/v1/prompts/support-reply/diff", params={"from": 2, "to": 2})
    ).json()
    assert same["template_diff"] == ""


async def test_diff_errors(editor_client: AsyncClient) -> None:
    await _create(editor_client)
    await _add_version(editor_client, "x")
    url = "/v1/prompts/support-reply/diff"
    assert (await editor_client.get(url, params={"from": 1, "to": 9})).status_code == 404
    assert (await editor_client.get(url, params={"from": 1, "to": "foo"})).status_code == 422
    assert (await editor_client.get(url, params={"from": 1})).status_code == 422
    missing = await editor_client.get("/v1/prompts/missing/diff", params={"from": 1, "to": 1})
    assert missing.status_code == 404
