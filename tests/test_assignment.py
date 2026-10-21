"""Deterministic assignment: pure functions and the ``assign`` endpoint."""

from __future__ import annotations

import uuid
from collections import Counter

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from promptlab.services import assignment
from tests.conftest import ClientFactory
from tests.experiment_factories import (
    create_experiment,
    running_experiment,
    seed_prompt,
    transition,
    variants,
)

SUBJECTS = [f"user-{i}" for i in range(10_000)]


def test_bucket_is_stable_and_in_range() -> None:
    assert assignment.bucket("abc") == assignment.bucket("abc")
    # Pinned value: the hash definition must never change, or live experiments would reshuffle.
    assert assignment.bucket("abc") == int("ba7816bf8f01cfe", 16) % 10_000
    assert all(0 <= assignment.bucket(s) < assignment.BUCKETS for s in SUBJECTS[:1000])


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ((1, 1), (5000, 10000)),
        ((1, 1, 1), (3334, 6667, 10000)),
        ((90, 10), (9000, 10000)),
        ((2, 1, 1), (5000, 7500, 10000)),
        ((1, 1, 1, 1, 1, 1, 1), (1429, 2858, 4287, 5716, 7144, 8572, 10000)),
        ((99_999, 1, 1), (9998, 9999, 10000)),  # minimum-one buckets taken from the largest
    ],
)
def test_variant_boundaries(weights: tuple[int, ...], expected: tuple[int, ...]) -> None:
    assert assignment.variant_boundaries(weights) == expected


def test_tiny_weights_still_get_a_bucket() -> None:
    bounds = assignment.variant_boundaries([1_000_000] * 9 + [1])
    sizes = [hi - lo for lo, hi in zip((0, *bounds), bounds, strict=False)]
    assert bounds[-1] == assignment.BUCKETS
    assert min(sizes) >= 1
    assert sizes[-1] == 1


@pytest.mark.parametrize("weights", [(), (1, 0), (-1, 2)])
def test_boundaries_reject_invalid_weights(weights: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="weights"):
        assignment.variant_boundaries(weights)


def test_boundaries_reject_too_many_variants() -> None:
    with pytest.raises(ValueError, match="too many"):
        assignment.variant_boundaries([1] * (assignment.BUCKETS + 1))


def _shares(weights: list[int], traffic: int = 100, salt: str = "s1") -> Counter[int | None]:
    return Counter(assignment.assign(salt, traffic, weights, s) for s in SUBJECTS)


def test_50_50_split() -> None:
    counts = _shares([50, 50])
    for index in (0, 1):
        assert 0.47 <= counts[index] / len(SUBJECTS) <= 0.53


def test_90_10_split() -> None:
    counts = _shares([90, 10])
    assert 0.08 <= counts[1] / len(SUBJECTS) <= 0.12


def test_three_equal_variants() -> None:
    counts = _shares([1, 1, 1])
    for index in range(3):
        assert 0.30 <= counts[index] / len(SUBJECTS) <= 0.37


def test_20_percent_traffic() -> None:
    enrolled = sum(assignment.is_enrolled("s1", 20, s) for s in SUBJECTS)
    assert 0.17 <= enrolled / len(SUBJECTS) <= 0.23
    assert sum(assignment.is_enrolled("s1", 100, s) for s in SUBJECTS) == len(SUBJECTS)


def test_traffic_gate_is_independent_of_variant_choice() -> None:
    weights = [1, 1]
    at_20 = {s: assignment.assign("s1", 20, weights, s) for s in SUBJECTS}
    at_60 = {s: assignment.assign("s1", 60, weights, s) for s in SUBJECTS}
    # Raising traffic only adds subjects; nobody already enrolled changes variant.
    for subject, variant in at_20.items():
        if variant is not None:
            assert at_60[subject] == variant
    # Enrolled subjects are still split evenly (the gate does not bias the variant hash).
    enrolled = Counter(v for v in at_20.values() if v is not None)
    assert 0.44 <= enrolled[0] / sum(enrolled.values()) <= 0.56


def test_salt_decorrelates_experiments() -> None:
    a = [assignment.choose_variant("exp-a", [1, 1], s) for s in SUBJECTS]
    b = [assignment.choose_variant("exp-b", [1, 1], s) for s in SUBJECTS]
    agreement = sum(x == y for x, y in zip(a, b, strict=True)) / len(SUBJECTS)
    assert 0.45 <= agreement <= 0.55


# ---------------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------------


async def _assign(client: AsyncClient, experiment_id: str, subject: str) -> dict[str, object]:
    response = await client.post(
        f"/v1/experiments/{experiment_id}/assign", json={"subject_id": subject}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_same_subject_same_variant(
    app: FastAPI, client: AsyncClient, runtime_client: AsyncClient
) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    first = await _assign(runtime_client, experiment["id"], "alice")
    second = await _assign(runtime_client, experiment["id"], "alice")
    assert first == second
    assert first["enrolled"] is True
    assert first["experiment_id"] == experiment["id"]
    assert first["subject_id"] == "alice"
    variant = first["variant"]
    assert isinstance(variant, dict)
    expected = assignment.assign(experiment["salt"], 100, [50, 50], "alice")
    assert variant == {
        "key": ["control", "treatment"][expected or 0],
        "version": [1, 2][expected or 0],
    }


async def test_api_split_matches_pure_function(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(
        client, variants=variants(("a", 1, 1), ("b", 2, 1), ("c", 3, 1))
    )
    for subject in SUBJECTS[:30]:
        body = await _assign(client, experiment["id"], subject)
        index = assignment.assign(experiment["salt"], 100, [1, 1, 1], subject)
        assert body["variant"] == {"key": "abc"[index or 0], "version": (index or 0) + 1}


async def test_not_enrolled_subject(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, traffic_percent=1, salt="fixed-salt")
    subject = next(s for s in SUBJECTS if not assignment.is_enrolled("fixed-salt", 1, s))
    body = await _assign(client, experiment["id"], subject)
    assert body["enrolled"] is False
    assert body["variant"] is None


async def test_paused_experiment_does_not_enroll(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await transition(client, experiment["id"], "pause")
    body = await _assign(client, experiment["id"], "alice")
    assert body == {
        "experiment_id": experiment["id"],
        "subject_id": "alice",
        "enrolled": False,
        "variant": None,
    }


async def test_draft_and_completed_do_not_enroll(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    draft = await create_experiment(client)
    assert (await _assign(client, draft["id"], "alice"))["enrolled"] is False
    await transition(client, draft["id"], "start")
    await transition(client, draft["id"], "complete")
    assert (await _assign(client, draft["id"], "alice"))["enrolled"] is False


async def test_assign_validation_and_errors(
    app: FastAPI, client: AsyncClient, client_for_role: ClientFactory
) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    url = f"/v1/experiments/{experiment['id']}/assign"
    assert (await client.post(url, json={"subject_id": ""})).status_code == 422
    assert (await client.post(url, json={"subject_id": "x" * 256})).status_code == 422
    missing = await client.post(f"/v1/experiments/{uuid.uuid4()}/assign", json={"subject_id": "a"})
    assert missing.status_code == 404
    runtime = await client_for_role("runtime")
    assert (await runtime.post(url, json={"subject_id": "a"})).status_code == 200
