# Spec Delta

## Purpose

Gives applications one call that returns exactly which prompt version to use for a given subject,
transparently applying a running experiment or falling back to a deployment label.

## ADDED Requirements

### Requirement: Resolve prompt for a subject
`POST /v1/prompts/{name}/resolve` SHALL accept optional `subject_id`, `label` (default `production`),
`variables` and `record_exposure` (default true). When a subject is enrolled in the prompt's running
experiment, the variant's version MUST be returned with experiment and variant identifiers; otherwise the
version the label points at MUST be returned with `experiment` null.

#### Scenario: Enrolled subject
- **WHEN** a running experiment exists on the prompt and an enrolled subject resolves the prompt
- **THEN** the response contains the variant's version and the experiment id and variant key

#### Scenario: No experiment
- **WHEN** no experiment is running and a client resolves label `production`
- **THEN** the response contains the version `production` points at and `experiment` null

#### Scenario: Unknown label
- **WHEN** no experiment applies and the requested label does not exist
- **THEN** the response status is 404

### Requirement: Experiment fallback label
When the caller omits `label` and the prompt has a running experiment, callers that are not enrolled
(including calls without `subject_id`) SHALL receive the version of the experiment's `fallback_label`;
an explicitly supplied `label` MUST always take precedence.

#### Scenario: Non-enrolled subject uses fallback label
- **WHEN** a running experiment with `fallback_label` `stable` exists and a non-enrolled subject resolves without `label`
- **THEN** the response contains the version `stable` points at and `experiment` null

#### Scenario: Explicit label wins
- **WHEN** the same subject resolves with `label` `production`
- **THEN** the response contains the version `production` points at

### Requirement: Exposure recording on resolve
When a subject is enrolled and `record_exposure` is true, resolving SHALL record one `exposure` event for
that subject and variant.

#### Scenario: Exposure counted
- **WHEN** an enrolled subject resolves the prompt with default options
- **THEN** the experiment results count one exposure for that subject's variant

### Requirement: Render on resolve
When `variables` are supplied, the response SHALL include the rendered text of the resolved version, applying
the same strict-variable and sandbox rules as rendering.

#### Scenario: Rendered output
- **WHEN** a client resolves with `variables: {"name": "Ada"}` and the resolved template is `Hi {{ name }}`
- **THEN** the response `rendered` is `Hi Ada`
