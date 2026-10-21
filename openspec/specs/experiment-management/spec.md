# experiment-management Specification

## Purpose
Defines A/B experiments between versions of one prompt and governs their lifecycle so traffic is only
split while an experiment is deliberately running.

## Requirements

### Requirement: Create experiment
Editors SHALL create an experiment for an existing prompt with a name unique per prompt, 2 to 10 variants
(unique `key`, existing `version` of that prompt, positive integer `weight`), `traffic_percent` 1–100
(default 100), `primary_metric` (default `conversion`) and `fallback_label` (default `production`).
New experiments start in `draft`.

#### Scenario: Experiment created
- **WHEN** an editor posts an experiment with variants `control` (v1, weight 50) and `treatment` (v2, weight 50)
- **THEN** the response status is 201 and the status is `draft`

#### Scenario: Too few variants
- **WHEN** an editor posts an experiment with a single variant
- **THEN** the response status is 422

#### Scenario: Variant references unknown version
- **WHEN** a variant references a version that does not exist for the prompt
- **THEN** the response status is 422

### Requirement: Control variant
Each experiment SHALL have exactly one control variant: the variant flagged `is_control`, or the first
variant when none is flagged. Flagging more than one MUST fail with 422.

#### Scenario: Implicit control
- **WHEN** no variant is flagged as control
- **THEN** the first variant is the control

### Requirement: Edit draft experiments
Editors SHALL update an experiment's variants, traffic, metric and fallback label only while it is in
`draft`; the description MAY be updated in any non-completed state. Other edits MUST fail with 409.

#### Scenario: Edit running experiment variants
- **WHEN** an editor patches the variants of a running experiment
- **THEN** the response status is 409

### Requirement: Lifecycle transitions
The service SHALL allow `start` (draft or paused → running), `pause` (running → paused) and `complete`
(running or paused → completed); any other transition MUST fail with 409 `invalid_state`. Starting MUST
fail with 409 when another experiment on the same prompt is running.

#### Scenario: Start experiment
- **WHEN** an editor starts a draft experiment
- **THEN** its status is `running` and `started_at` is set

#### Scenario: Second running experiment rejected
- **WHEN** an editor starts an experiment while another on the same prompt is running
- **THEN** the response status is 409

#### Scenario: Restart completed experiment
- **WHEN** an editor starts a completed experiment
- **THEN** the response status is 409 and the code is `invalid_state`

### Requirement: Complete with promotion
Completing an experiment SHALL accept an optional `winner` variant key and optional `promote_label`;
when both are supplied the label MUST be moved to the winner's version and recorded in label history.
`promote_label` without `winner` MUST fail with 422.

#### Scenario: Promote winner to production
- **WHEN** an editor completes an experiment with `winner: treatment` and `promote_label: production`
- **THEN** the experiment is `completed`, its winner is `treatment` and `production` points at the treatment version

### Requirement: List and fetch experiments
Clients SHALL list experiments with pagination and optional `prompt` and `status` filters and fetch one by id.

#### Scenario: Filter by status
- **WHEN** a client calls `GET /v1/experiments?status=running`
- **THEN** only running experiments are returned
