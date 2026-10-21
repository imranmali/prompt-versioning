# A/B testing prompt versions

PromptLab can split live traffic between versions of a prompt, attribute outcomes to the version
each subject saw and tell you, with a fixed-horizon statistical test, whether a version wins.

This guide covers the concepts, the experiment lifecycle, how subjects are assigned, how events are
ingested, how results are computed and how to read them.

## Concepts

| Term | Meaning |
| --- | --- |
| **Experiment** | A test on **one prompt** with 2 to 10 variants. Its name is unique per prompt. |
| **Variant** | A key (`control`, `treatment`, ...) pinned to a **version number** of the prompt, with an integer **weight**. |
| **Control** | The baseline every other variant is compared with. It is the variant flagged `is_control`, or the first variant when none is flagged. At most one variant can be flagged. |
| **Subject** | Whatever you randomize on: a user id, a session id, a conversation id. Use the same `subject_id` everywhere. |
| **Traffic percent** | Share of subjects (1 to 100) enrolled in the experiment. Subjects outside it are served the fallback label. |
| **Fallback label** | Label (default `production`) served to traffic that is not enrolled while the experiment runs. |
| **Exposure** | An event named `exposure`: the subject was served the variant. Exposures define who is in the experiment. |
| **Metric** | Any other event name (`conversion`, `thumbs_up`, `latency_ms`, ...). `primary_metric` (default `conversion`) is the one results use by default. |

## Lifecycle

```
draft ──start──▶ running ──pause──▶ paused
                    ▲                 │
                    └──────start──────┘
running / paused ──complete──▶ completed
```

* New experiments start in `draft`. Only drafts can change variants, `traffic_percent`,
  `primary_metric` or `fallback_label` (`PATCH`). The description can be edited in any state except
  `completed`. Completed experiments cannot be modified at all.
* `start` moves a draft or paused experiment to `running` and sets `started_at` on the first start.
  Only **one experiment per prompt** can run at a time; starting a second one fails with
  `409 conflict`.
* `pause` stops enrollment. Paused experiments still accept events for subjects already exposed.
* `complete` ends the experiment for good, sets `ended_at` and optionally records a `winner`. With
  `promote_label`, the label is moved to the winner's version in the same transaction (and recorded
  in the label history with your API key's name as the actor).
* Any other transition fails with `409 invalid_state`.

Creating, editing and lifecycle calls need an `editor` key; reading, assignment, resolution, events
and results work with a `runtime` key.

## Quick start (curl)

```bash
export PL=http://localhost:8000
export EDITOR="X-API-Key: pl_editor_key"
export RUNTIME="X-API-Key: pl_runtime_key"

# 1. Create a 50/50 experiment between versions 1 and 2 of the prompt "greet".
curl -s -X POST $PL/v1/experiments -H "$EDITOR" -H 'Content-Type: application/json' -d '{
  "prompt": "greet",
  "name": "friendlier-greeting",
  "description": "Does the informal greeting convert better?",
  "variants": [
    {"key": "control",   "version": 1, "weight": 50},
    {"key": "treatment", "version": 2, "weight": 50}
  ],
  "traffic_percent": 100,
  "primary_metric": "conversion"
}'
# -> 201 {"id": "6f0c...", "status": "draft", "salt": "9b1e4c2a7d3f5e60", ...}

# 2. Start it.
curl -s -X POST $PL/v1/experiments/$EXP/start -H "$EDITOR"

# 3. In your application: resolve the prompt for each subject (records an exposure).
curl -s -X POST $PL/v1/prompts/greet/resolve -H "$RUNTIME" -H 'Content-Type: application/json' \
  -d '{"subject_id": "user-42", "variables": {"name": "Ada"}}'
# -> {"prompt": "greet", "version": 2, "label": null, "template": "Hi {{ name }}",
#     "model_settings": {...}, "rendered": "Hi Ada",
#     "experiment": {"id": "6f0c...", "name": "friendlier-greeting", "variant": "treatment"}}

# 4. Report outcomes (batch up to 1000 events; event_id makes retries safe).
curl -s -X POST $PL/v1/events -H "$RUNTIME" -H 'Content-Type: application/json' -d '{
  "events": [
    {"experiment_id": "'$EXP'", "subject_id": "user-42", "name": "conversion", "event_id": "order-981"},
    {"experiment_id": "'$EXP'", "subject_id": "user-42", "name": "revenue", "value": 19.9}
  ]
}'
# -> 202 {"accepted": 2, "duplicates": 0, "skipped": 0}

# 5. Read the results.
curl -s "$PL/v1/experiments/$EXP/results" -H "$RUNTIME"
curl -s "$PL/v1/experiments/$EXP/results?metric=revenue&kind=numeric&alpha=0.01" -H "$RUNTIME"

# 6. Finish and ship the winner.
curl -s -X POST $PL/v1/experiments/$EXP/complete -H "$EDITOR" -H 'Content-Type: application/json' \
  -d '{"winner": "treatment", "promote_label": "production"}'
```

Other endpoints:

* `GET /v1/experiments?prompt=greet&status=running&limit=50&offset=0`: list experiments, newest first.
* `GET /v1/experiments/{id}`: fetch one.
* `PATCH /v1/experiments/{id}`: partial update (see lifecycle rules above).
* `POST /v1/experiments/{id}/assign` with `{"subject_id": "user-42"}`: returns
  `{"enrolled": true, "variant": {"key": "treatment", "version": 2}}` **without recording
  anything**. Use it when you call your LLM with a version obtained elsewhere; then send the
  `exposure` event yourself.

## Assignment

Assignment is a pure function of the experiment's salt, traffic percentage, variant weights and
the subject id. Nothing is stored, so every replica returns the same answer and assignment costs
no database write:

```
bucket(x)  = int(sha256(x).hexdigest()[:15], 16) % 10000
enrolled   = bucket(f"{salt}:traffic:{subject_id}") < traffic_percent * 100
variant    = the variant whose range contains bucket(f"{salt}:variant:{subject_id}")
```

The 10,000 buckets are split between variants in proportion to their weights (largest-remainder
rounding; every variant gets at least one bucket). For example weights `1/1/1` give the ranges
`[0, 3334)`, `[3334, 6667)` and `[6667, 10000)`.

Properties worth knowing:

* **Sticky**: a subject always gets the same variant for a given experiment.
* **Independent gate**: the traffic gate and the variant choice hash different inputs. Raising
  `traffic_percent` only adds subjects; no enrolled subject switches variant. (Traffic can only be
  changed in `draft`, but the property also keeps the split unbiased.)
* **Decorrelated experiments**: each experiment gets a random salt (or the one you pass), so being
  in `treatment` in one experiment says nothing about the next one. Reuse a salt only if you
  deliberately want identical assignments.
* Only `running` experiments enroll; `assign` and `resolve` treat paused, draft and completed
  experiments as "not enrolled".

## Resolution

`POST /v1/prompts/{name}/resolve` with `{subject_id?, label = "production", variables?,
record_exposure = true}`:

1. If `subject_id` is given and the prompt has a running experiment that enrolls the subject, the
   variant's version is returned with `experiment: {id, name, variant}` and `label: null`. When
   `record_exposure` is true, one `exposure` event is stored.
2. Otherwise the version a label points at is returned with `experiment: null`. While an
   experiment runs, traffic outside it gets the experiment's `fallback_label` unless you pass
   `label` explicitly. A missing label gives `404`.
3. With `variables`, the response includes `rendered` text using the same strict, sandboxed rules
   as rendering (`422 missing_variables` / `422 invalid_template`). A failed render records no
   exposure.

Running experiments are looked up through a per-instance cache
(`PROMPTLAB_RESOLVE_CACHE_TTL_SECONDS`, default 2 s, `0` disables it). Starting, pausing,
completing or editing an experiment invalidates the entry on the instance that handled the call;
other replicas pick up the change within the TTL.

## Events

`POST /v1/events` accepts 1 to 1000 events:

| Field | Notes |
| --- | --- |
| `experiment_id` | Must exist, otherwise the **whole batch** is rejected with `422` and nothing is stored. |
| `subject_id` | 1 to 255 characters. |
| `name` | `exposure` or a metric name matching `^[a-z0-9][a-z0-9_.-]{0,63}$`. |
| `value` | Finite number, default `1`. Used by numeric metrics. |
| `variant` | Optional variant key. Unknown keys reject the batch with `422`. When omitted, the subject's deterministic assignment is used. An explicit key is trusted as-is. |
| `event_id` | Optional (up to 128 characters). Deduplicates per experiment: re-sent ids count as `duplicates`, as do repeats within one batch. |
| `timestamp` | Optional; defaults to the ingestion time. |

The response is `202 {"accepted", "duplicates", "skipped"}`. Events are **skipped** when the
experiment is neither running nor paused, or when the variant is omitted and the subject is not
enrolled. Always send an `event_id` for events you may retry; events without one are never
deduplicated.

## Results

`GET /v1/experiments/{id}/results?metric=&kind=binary|numeric&alpha=0.05`

* `metric` defaults to the experiment's `primary_metric`.
* `alpha` (between 0 and 0.5) is the significance level. Intervals are reported at confidence
  `1 - alpha` (95% by default).
* Every statistic that is undefined (no samples, zero variance, zero control value for a relative
  lift) is `null`, never NaN.

### Binary metrics (`kind=binary`, default)

Per variant:

* `exposures`: distinct subjects with an exposure in the variant.
* `conversions`: distinct exposed subjects with at least one `metric` event **in the same
  variant**. Metric events from subjects who were never exposed in that variant are ignored.
* `rate = conversions / exposures`, with a **Wilson score interval** (`ci_low`, `ci_high`).
* For non-control variants: `lift_abs = rate - control_rate`, `lift_rel = lift_abs /
  control_rate` and the two-sided **pooled two-proportion z-test** `p_value`.

### Numeric metrics (`kind=numeric`)

Per variant: `count` (number of metric events), `mean`, sample standard deviation `std` (n - 1)
and a Student-t interval `mean ± t(1 - alpha/2, n - 1) · std / sqrt(n)`. Non-control variants get
`lift_abs = mean - control_mean`, `lift_rel` and **Welch's t-test** `p_value` (Welch-Satterthwaite
degrees of freedom). Means and variances are computed in SQL from `COUNT`, `SUM(value)` and
`SUM(value²)`; with very large values and tiny spreads this can lose precision.

Numeric metrics count every metric event attributed to the variant (one value per event). If you
want one value per subject (e.g. revenue per user), aggregate on your side and send one event per
subject.

### Sample ratio mismatch (`srm`)

A Pearson chi-square test compares exposures per variant with the configured weights.
`mismatch: true` when its p-value is below **0.001**. A mismatch means assignment or exposure
logging is broken (bots filtered in one arm only, exposures logged only on success, caching in front
of one variant, ...). **Do not trust the other numbers until you find the cause.**

### Winner

`winner` is the non-control variant with `p_value < alpha` and the **largest positive**
`lift_abs`, or `null`. A variant can be `significant` with a negative lift (it is significantly
**worse**); it is never reported as the winner.

### Example

```json
{
  "experiment_id": "6f0c...", "metric": "conversion", "kind": "binary", "alpha": 0.05,
  "total_exposures": 2000,
  "srm": {"chi_square": 0.0, "p_value": 1.0, "mismatch": false},
  "variants": [
    {"key": "control", "version": 1, "is_control": true, "exposures": 1000, "conversions": 100,
     "rate": 0.1, "ci_low": 0.0829, "ci_high": 0.1202,
     "lift_abs": null, "lift_rel": null, "p_value": null, "significant": false},
    {"key": "treatment", "version": 2, "is_control": false, "exposures": 1000, "conversions": 150,
     "rate": 0.15, "ci_low": 0.1292, "ci_high": 0.1735,
     "lift_abs": 0.05, "lift_rel": 0.5, "p_value": 0.00072, "significant": true}
  ],
  "winner": "treatment"
}
```

Read it as: the treatment converts 15.0% vs 10.0% (+5 points, +50% relative). If there were no
real difference, a gap at least this large would appear about 0.07% of the time, so it is
significant at the 5% level and reported as the winner. Exposures match the 50/50 weights.

## Interpreting results responsibly

* **Decide the sample size up front and do not peek.** The tests are fixed-horizon: checking
  results every day and stopping as soon as `significant` turns true inflates the false-positive
  rate far above `alpha`. Sequential testing corrections are out of scope. Pick a duration (at
  least one full weekly cycle) or a sample size from a power calculation and read the result once.
* **Multiple comparisons.** With several treatments, or several metrics inspected, the chance that
  one of them is "significant" by luck grows. Use a stricter `alpha` (e.g. `0.05 / number of
  comparisons`) when you look at many.
* **Check SRM first.** A mismatch invalidates the comparison.
* **Look at intervals, not only p-values.** A significant but tiny lift may not be worth shipping;
  a non-significant result with a wide interval means "not enough data", not "no effect".
* **Exposure is the denominator.** Log the exposure when the subject actually sees the output
  (resolve does this for you). Conversions without a matching exposure are ignored.
* **Do not change the experiment while it runs.** Variants, weights and traffic are frozen once
  started; create a new experiment instead.
* **Novelty and seasonality** effects are not modeled; long-running effects may differ from the
  first days.
