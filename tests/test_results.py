"""Experiment results: binary and numeric metrics, SRM and winner selection."""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from promptlab.models import EXPOSURE_EVENT
from promptlab.services import stats
from tests.experiment_factories import (
    insert_events,
    running_experiment,
    seed_binary,
    seed_numeric,
    seed_prompt,
    variant_ids,
    variants,
)


async def _results(client: AsyncClient, experiment_id: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"/v1/experiments/{experiment_id}/results", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _by_key(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {v["key"]: v for v in results["variants"]}


async def test_clear_winner(app: FastAPI, client: AsyncClient, runtime_client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_binary(app, experiment, {"control": (1000, 100), "treatment": (1000, 150)})

    results = await _results(runtime_client, experiment["id"])
    assert results["experiment_id"] == experiment["id"]
    assert results["metric"] == "conversion"
    assert results["kind"] == "binary"
    assert results["alpha"] == 0.05
    assert results["total_exposures"] == 2000
    assert results["srm"]["mismatch"] is False
    assert results["srm"]["chi_square"] == pytest.approx(0.0)
    assert results["srm"]["p_value"] == pytest.approx(1.0)

    by_key = _by_key(results)
    control, treatment = by_key["control"], by_key["treatment"]
    assert (control["exposures"], control["conversions"]) == (1000, 100)
    assert control["rate"] == pytest.approx(0.1)
    assert control["version"] == 1
    assert control["is_control"] is True
    assert control["lift_abs"] is None
    assert control["lift_rel"] is None
    assert control["p_value"] is None
    assert control["significant"] is False
    low, high = stats.wilson_interval(100, 1000) or (0.0, 0.0)
    assert control["ci_low"] == pytest.approx(low)
    assert control["ci_high"] == pytest.approx(high)

    assert (treatment["exposures"], treatment["conversions"]) == (1000, 150)
    assert treatment["rate"] == pytest.approx(0.15)
    assert treatment["lift_abs"] == pytest.approx(0.05)
    assert treatment["lift_rel"] == pytest.approx(0.5)
    assert treatment["p_value"] == pytest.approx(0.000723232716, rel=1e-6)
    assert treatment["p_value"] < 0.05
    assert treatment["significant"] is True
    assert results["winner"] == "treatment"
    assert set(control) == {
        "key",
        "version",
        "is_control",
        "exposures",
        "conversions",
        "rate",
        "ci_low",
        "ci_high",
        "lift_abs",
        "lift_rel",
        "p_value",
        "significant",
    }


async def test_no_difference(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_binary(app, experiment, {"control": (1000, 100), "treatment": (1000, 100)})
    results = await _results(client, experiment["id"])
    treatment = _by_key(results)["treatment"]
    assert treatment["lift_abs"] == pytest.approx(0.0)
    assert treatment["p_value"] == pytest.approx(1.0)
    assert treatment["significant"] is False
    assert results["winner"] is None


async def test_custom_alpha(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_binary(app, experiment, {"control": (1000, 100), "treatment": (1000, 131)})

    default = await _results(client, experiment["id"])
    p_value = _by_key(default)["treatment"]["p_value"]
    assert p_value == pytest.approx(0.03, abs=0.005)
    assert default["winner"] == "treatment"

    strict = await _results(client, experiment["id"], alpha=0.01)
    assert strict["alpha"] == 0.01
    assert _by_key(strict)["treatment"]["significant"] is False
    assert strict["winner"] is None
    # The confidence interval follows the confidence level 1 - alpha.
    assert _by_key(strict)["control"]["ci_low"] < _by_key(default)["control"]["ci_low"]


async def test_winner_is_largest_significant_positive_lift(
    app: FastAPI, client: AsyncClient
) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(
        client,
        variants=variants(("base", 1, 1), ("good", 2, 1), ("best", 3, 1), ("bad", 1, 1)),
    )
    await seed_binary(
        app,
        experiment,
        {"base": (1000, 100), "good": (1000, 150), "best": (1000, 180), "bad": (1000, 50)},
    )
    results = await _results(client, experiment["id"])
    by_key = _by_key(results)
    assert by_key["bad"]["significant"] is True
    assert by_key["bad"]["lift_abs"] < 0
    assert by_key["good"]["significant"] is True
    assert results["winner"] == "best"


async def test_conversions_require_exposure_in_same_variant(
    app: FastAPI, client: AsyncClient
) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    ids = variant_ids(experiment)
    exp_id = uuid.UUID(experiment["id"])

    def row(subject: str, variant: str, name: str) -> dict[str, Any]:
        return {
            "experiment_id": exp_id,
            "variant_id": ids[variant],
            "subject_id": subject,
            "name": name,
        }

    await insert_events(
        app,
        [
            # a: exposed twice, converted three times -> counted once.
            row("a", "control", EXPOSURE_EVENT),
            row("a", "control", EXPOSURE_EVENT),
            row("a", "control", "conversion"),
            row("a", "control", "conversion"),
            row("a", "control", "conversion"),
            # b: exposed in control but converted in treatment -> not a conversion anywhere.
            row("b", "control", EXPOSURE_EVENT),
            row("b", "treatment", "conversion"),
            # c: converted without exposure -> ignored.
            row("c", "treatment", "conversion"),
            # d: exposed in treatment, converted on another metric only.
            row("d", "treatment", EXPOSURE_EVENT),
            row("d", "treatment", "signup"),
        ],
    )
    by_key = _by_key(await _results(client, experiment["id"]))
    assert (by_key["control"]["exposures"], by_key["control"]["conversions"]) == (2, 1)
    assert (by_key["treatment"]["exposures"], by_key["treatment"]["conversions"]) == (1, 0)
    signup = _by_key(await _results(client, experiment["id"], metric="signup"))
    assert signup["treatment"]["conversions"] == 1


async def test_empty_experiment_uses_nulls(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    results = await _results(client, experiment["id"])
    assert results["total_exposures"] == 0
    assert results["srm"] == {"chi_square": None, "p_value": None, "mismatch": False}
    for variant in results["variants"]:
        assert variant["exposures"] == 0
        assert variant["conversions"] == 0
        for field in ("rate", "ci_low", "ci_high", "lift_abs", "lift_rel", "p_value"):
            assert variant[field] is None
        assert variant["significant"] is False
    assert results["winner"] is None

    numeric = await _results(client, experiment["id"], kind="numeric", metric="score")
    for variant in numeric["variants"]:
        assert variant["count"] == 0
        assert variant["mean"] is None
        assert variant["std"] is None
        assert variant["ci_low"] is None


async def test_zero_control_rate_has_no_relative_lift(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_binary(app, experiment, {"control": (100, 0), "treatment": (100, 10)})
    treatment = _by_key(await _results(client, experiment["id"]))["treatment"]
    assert treatment["lift_abs"] == pytest.approx(0.1)
    assert treatment["lift_rel"] is None
    assert treatment["p_value"] is not None


async def test_numeric_difference(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    control = [4.0 + (0.1 if i % 2 else -0.1) for i in range(200)]
    treatment = [4.5 + (0.1 if i % 2 else -0.1) for i in range(200)]
    await seed_numeric(app, experiment, {"control": control, "treatment": treatment})

    results = await _results(client, experiment["id"], metric="rating", kind="numeric")
    assert results["kind"] == "numeric"
    assert results["metric"] == "rating"
    by_key = _by_key(results)
    c, t = by_key["control"], by_key["treatment"]
    assert c["count"] == 200
    assert c["exposures"] == 200
    assert c["mean"] == pytest.approx(4.0)
    assert c["std"] == pytest.approx(math.sqrt(200 * 0.01 / 199))
    assert c["ci_low"] < 4.0 < c["ci_high"]
    assert c["p_value"] is None
    assert t["mean"] == pytest.approx(4.5)
    assert t["lift_abs"] == pytest.approx(0.5)
    assert t["lift_rel"] == pytest.approx(0.125)
    assert t["p_value"] < 1e-10
    assert t["significant"] is True
    assert results["winner"] == "treatment"
    assert "conversions" not in t
    assert "rate" not in t


async def test_numeric_matches_reference_welch(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_numeric(
        app, experiment, {"control": [1, 2, 3, 4], "treatment": [2, 4, 6, 8, 10]}, metric="score"
    )
    results = await _results(client, experiment["id"], metric="score", kind="numeric")
    t = _by_key(results)["treatment"]
    assert t["p_value"] == pytest.approx(0.0691336, abs=1e-6)
    assert t["significant"] is False
    assert results["winner"] is None
    c = _by_key(results)["control"]
    half = stats.student_t_ppf(0.975, 3) * math.sqrt(5 / 3) / 2
    assert c["ci_low"] == pytest.approx(2.5 - half)
    assert c["ci_high"] == pytest.approx(2.5 + half)


async def test_numeric_degenerate_samples(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_numeric(app, experiment, {"control": [5.0] * 10, "treatment": [5.0] * 10})
    results = await _results(client, experiment["id"], metric="rating", kind="numeric")
    for variant in results["variants"]:
        assert variant["std"] == pytest.approx(0.0)
        assert variant["ci_low"] == pytest.approx(5.0)
        assert variant["ci_high"] == pytest.approx(5.0)
    assert _by_key(results)["treatment"]["p_value"] is None  # zero variance
    assert results["winner"] is None


async def test_numeric_single_sample(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_numeric(app, experiment, {"control": [1.0, 2.0, 3.0], "treatment": [7.0]})
    by_key = _by_key(await _results(client, experiment["id"], metric="rating", kind="numeric"))
    t = by_key["treatment"]
    assert t["count"] == 1
    assert t["mean"] == pytest.approx(7.0)
    assert t["std"] is None
    assert t["ci_low"] is None
    assert t["lift_abs"] == pytest.approx(5.0)
    assert t["p_value"] is None
    assert t["significant"] is False


async def test_numeric_zero_control_mean(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_numeric(app, experiment, {"control": [-1.0, 1.0], "treatment": [1.0, 2.0]})
    t = _by_key(await _results(client, experiment["id"], metric="rating", kind="numeric"))[
        "treatment"
    ]
    assert t["lift_abs"] == pytest.approx(1.5)
    assert t["lift_rel"] is None


async def test_skewed_exposures(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    await seed_binary(app, experiment, {"control": (1000, 0), "treatment": (700, 0)})
    srm = (await _results(client, experiment["id"]))["srm"]
    assert srm["mismatch"] is True
    assert srm["chi_square"] == pytest.approx(52.941176, abs=1e-5)
    assert srm["p_value"] < 0.001


async def test_srm_respects_weights(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(
        client, variants=variants(("control", 1, 90), ("treatment", 2, 10))
    )
    await seed_binary(app, experiment, {"control": (900, 0), "treatment": (100, 0)})
    srm = (await _results(client, experiment["id"]))["srm"]
    assert srm["mismatch"] is False
    assert srm["chi_square"] == pytest.approx(0.0)


async def test_primary_metric_is_default(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client, primary_metric="signup")
    await seed_binary(app, experiment, {"control": (10, 5), "treatment": (10, 2)}, metric="signup")
    results = await _results(client, experiment["id"])
    assert results["metric"] == "signup"
    assert _by_key(results)["control"]["conversions"] == 5


async def test_results_validation(app: FastAPI, client: AsyncClient) -> None:
    await seed_prompt(app)
    experiment = await running_experiment(client)
    url = f"/v1/experiments/{experiment['id']}/results"
    for params in (
        {"alpha": 0},
        {"alpha": 0.5},
        {"alpha": -1},
        {"kind": "bogus"},
        {"metric": "Bad Metric"},
        {"metric": "exposure"},
    ):
        assert (await client.get(url, params=params)).status_code == 422, params
    assert (await client.get(f"/v1/experiments/{uuid.uuid4()}/results")).status_code == 404
