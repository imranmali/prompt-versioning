# Spec Delta

## Purpose

Assigns each subject (user, session, conversation) to an experiment variant deterministically, so
assignment is sticky, uniform and consistent across stateless replicas.

## ADDED Requirements

### Requirement: Deterministic sticky assignment
Assignment SHALL be a pure function of the experiment's salt, its traffic percentage, its variant weights
and the `subject_id`; the same inputs MUST always yield the same variant on every replica, without storing
assignments.

#### Scenario: Same subject same variant
- **WHEN** a client calls `POST /v1/experiments/{id}/assign` twice with the same `subject_id`
- **THEN** both responses return the same variant

### Requirement: Weighted allocation
Among enrolled subjects, the share assigned to each variant SHALL converge to its weight divided by the
total weight.

#### Scenario: 50/50 split
- **WHEN** 10,000 distinct subjects are assigned in a 50/50 experiment
- **THEN** each variant receives between 47% and 53% of subjects

#### Scenario: 90/10 split
- **WHEN** 10,000 distinct subjects are assigned in a 90/10 experiment
- **THEN** the minority variant receives between 8% and 12% of subjects

### Requirement: Traffic percentage gating
Only `traffic_percent` percent of subjects SHALL be enrolled; non-enrolled subjects MUST receive
`enrolled: false` and no variant. The traffic gate MUST be independent of variant selection.

#### Scenario: 20 percent traffic
- **WHEN** 10,000 distinct subjects are assigned in an experiment with `traffic_percent` 20
- **THEN** between 17% and 23% are enrolled

### Requirement: Only running experiments enroll
Experiments that are not `running` SHALL NOT enroll subjects; assignment MUST return `enrolled: false`.

#### Scenario: Paused experiment
- **WHEN** a client assigns a subject to a paused experiment
- **THEN** the response has `enrolled` false
