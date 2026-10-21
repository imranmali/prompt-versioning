# Proposal: A/B testing of prompt versions

## Why

Prompt changes are usually shipped on gut feeling. To know whether version B actually beats version A,
teams need to split live traffic between versions, attribute outcomes to the version a user saw and get a
statistically sound verdict — without writing bespoke bucketing and statistics code in every application.

## What Changes

- Experiments on a prompt with 2–10 weighted variants, each pinned to a prompt version, a control variant,
  a traffic percentage and a lifecycle `draft → running ⇄ paused → completed`.
- Deterministic, sticky, stateless subject assignment (hash-based bucketing) so any replica returns the same
  variant for the same subject without a database write.
- `resolve` endpoint: one call returns the prompt version (experiment variant or label fallback) and optionally
  the rendered text, recording an exposure.
- Batched, idempotent event ingestion (exposures, conversions, numeric metrics).
- Results with per-variant statistics: conversion rate or mean, 95% confidence intervals, lift vs control,
  p-values (two-proportion z-test / Welch's t-test), sample-ratio-mismatch check and winner detection.
- Completing an experiment can promote the winner's version to a label in the same call.

## Capabilities

### New Capabilities
- `experiment-management`: experiment definition, validation and lifecycle.
- `experiment-assignment`: deterministic traffic allocation and variant assignment.
- `experiment-analytics`: event ingestion and statistical results.
- `prompt-resolution`: experiment-aware retrieval of the prompt version to serve.

### Modified Capabilities
- None.

## Out of Scope

- Multi-armed bandits / adaptive allocation, sequential testing corrections, Bayesian analysis.
- More than one simultaneously running experiment per prompt.
- Streaming analytics pipelines; results are computed from the relational store on request.

## Impact

- New `/v1/experiments`, `/v1/events` and `/v1/prompts/{name}/resolve` endpoints.
- Uses tables `experiments`, `experiment_variants`, `events` and the label service from `add-prompt-versioning`.
