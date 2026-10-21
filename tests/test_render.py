"""Rendering prompts by version, label or latest with strict, sandboxed templates."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

BASE = "/v1/prompts/greet"


async def _setup(client: AsyncClient, *templates: str, **settings: Any) -> None:
    assert (await client.post("/v1/prompts", json={"name": "greet"})).status_code == 201
    for template in templates:
        response = await client.post(
            f"{BASE}/versions", json={"template": template, "model_settings": settings}
        )
        assert response.status_code == 201, response.text


async def test_render_by_label(editor_client: AsyncClient, runtime_client: AsyncClient) -> None:
    await _setup(editor_client, "Hello {{ name }}", "Hi {{ name }}", "Hey {{ name }}", model="m")
    await editor_client.put(f"{BASE}/labels/production", json={"version": 2})

    response = await runtime_client.post(
        f"{BASE}/render", json={"label": "production", "variables": {"name": "Ada"}}
    )
    assert response.status_code == 200
    assert response.json() == {
        "prompt": "greet",
        "version": 2,
        "label": "production",
        "rendered": "Hi Ada",
        "model_settings": {"model": "m"},
    }


async def test_render_latest_by_default(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hello {{ name }}", "Hey {{ name }}!")
    response = await editor_client.post(f"{BASE}/render", json={"variables": {"name": "Ada"}})
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["label"] is None
    assert body["rendered"] == "Hey Ada!"
    assert body["model_settings"] == {}


async def test_render_by_version(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hello {{ name }}", "Hey {{ name }}!", temperature=0.3)
    response = await editor_client.post(
        f"{BASE}/render", json={"version": 1, "variables": {"name": "Ada"}}
    )
    assert response.status_code == 200
    assert response.json()["rendered"] == "Hello Ada"
    assert response.json()["version"] == 1
    assert response.json()["model_settings"] == {"temperature": 0.3}


async def test_render_without_variables(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Static text\n")
    response = await editor_client.post(f"{BASE}/render", json={})
    assert response.status_code == 200
    assert response.json()["rendered"] == "Static text\n"


async def test_render_ignores_extra_variables_and_supports_logic(
    editor_client: AsyncClient,
) -> None:
    await _setup(editor_client, "{% for item in items %}{{ item | upper }} {% endfor %}")
    response = await editor_client.post(
        f"{BASE}/render", json={"variables": {"items": ["a", "b"], "unused": 1}}
    )
    assert response.json()["rendered"] == "A B "


async def test_both_version_and_label(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hi {{ name }}")
    await editor_client.put(f"{BASE}/labels/production", json={"version": 1})
    response = await editor_client.post(
        f"{BASE}/render",
        json={"version": 1, "label": "production", "variables": {"name": "Ada"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {"variables": []},
        {"version": "one"},
        {"version": 0},
        {"label": "Bad Label"},
        {"extra": True},
    ],
)
async def test_invalid_render_payload(editor_client: AsyncClient, payload: dict[str, Any]) -> None:
    await _setup(editor_client, "Hi")
    assert (await editor_client.post(f"{BASE}/render", json=payload)).status_code == 422


async def test_missing_variable(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hi {{ name }} from {{ city }}")
    response = await editor_client.post(f"{BASE}/render", json={"variables": {"name": "Ada"}})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "missing_variables"
    assert error["details"] == {"missing": ["city"]}


async def test_all_missing_variables_listed(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "{{ greeting }} {{ name }} from {{ city }}")
    response = await editor_client.post(f"{BASE}/render", json={"variables": {"name": "Ada"}})
    assert response.json()["error"]["details"] == {"missing": ["city", "greeting"]}


async def test_unsafe_attribute_access(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "{{ name.__class__.__mro__ }}")
    response = await editor_client.post(f"{BASE}/render", json={"variables": {"name": "Ada"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_template"


async def test_unsafe_method_call(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "{{ ''.__class__.__subclasses__() }}")
    response = await editor_client.post(f"{BASE}/render", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_template"


async def test_render_unknown_label(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hi")
    response = await editor_client.post(f"{BASE}/render", json={"label": "production"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_render_unknown_version(editor_client: AsyncClient) -> None:
    await _setup(editor_client, "Hi")
    response = await editor_client.post(f"{BASE}/render", json={"version": 7})
    assert response.status_code == 404


async def test_render_prompt_without_versions(editor_client: AsyncClient) -> None:
    await _setup(editor_client)
    response = await editor_client.post(f"{BASE}/render", json={})
    assert response.status_code == 404


async def test_render_unknown_prompt(editor_client: AsyncClient) -> None:
    response = await editor_client.post("/v1/prompts/missing/render", json={})
    assert response.status_code == 404


async def test_render_requires_authentication(anon_client: AsyncClient) -> None:
    assert (await anon_client.post(f"{BASE}/render", json={})).status_code == 401
