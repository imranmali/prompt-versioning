# experiment-analytics Specification

## Purpose
Collects exposure and outcome events for experiments and turns them into statistically sound per-variant
results so teams can decide which prompt version wins.

## Requirements

### Requirement: Batched event ingestion
Runtime clients SHALL submit 1–1000 events per `POST /v1/events` call; each event has `experiment_id`,
`subject_id`, `name` (`exposure` or a metric name), optional numeric `value` (default 1), optional `variant`
key and optional `event_id`. The response MUST be 202 with counts of `accepted`, `duplicates` and `skipped` events.

#### Scenario: Accept batch
- **WHEN** a client posts three valid events for a running experiment
- **THEN** the response status is 202 and `accepted` is 3

#### Scenario: Oversized batch
- **WHEN** a client posts 1001 events
- **THEN** the response status is 422

#### Scenario: Unknown experiment
- **WHEN** an event references an experiment id that does not exist
- **THEN** the response status is 422 and no event of the batch is stored

### Requirement: Variant attribution
When an event omits `variant`, the service SHALL attribute it to the subject's deterministic assignment.
Events for subjects not enrolled, or for experiments that are neither running nor paused, MUST be counted as `skipped`.

#### Scenario: Implicit variant
- **WHEN** an event without `variant` is ingested for an enrolled subject
- **THEN** it is stored under the variant `assign` returns for that subject

#### Scenario: Draft experiment events skipped
- **WHEN** events are posted for a draft experiment
- **THEN** they are counted as `skipped`

### Requirement: Idempotent events
Events with an `event_id` already stored for the same experiment SHALL NOT be stored again and MUST be
counted as `duplicates`.

#### Scenario: Retried batch
- **WHEN** a client re-posts a batch whose events carry the same `event_id`s
- **THEN** `duplicates` equals the batch size and stored counts do not change

### Requirement: Binary metric results
For a binary metric the results SHALL report per variant the number of exposed subjects, the number of
exposed subjects with at least one metric event, the conversion rate with a 95% Wilson interval and, for
non-control variants, absolute and relative lift vs control with a two-sided two-proportion z-test p-value.

#### Scenario: Clear winner
- **WHEN** control converts 100 of 1000 exposed subjects and treatment converts 150 of 1000
- **THEN** the treatment p-value is below 0.05, it is marked significant and reported as the winner

#### Scenario: No difference
- **WHEN** both variants convert 100 of 1000 exposed subjects
- **THEN** the treatment is not significant and no winner is reported

### Requirement: Numeric metric results
For a numeric metric (`kind=numeric`) the results SHALL report per variant the sample count, mean, standard
deviation and 95% confidence interval and, for non-control variants, lift vs control with a Welch's t-test p-value.

#### Scenario: Numeric difference
- **WHEN** control values average 4.0 and treatment values average 4.5 with low variance over 200 samples each
- **THEN** the treatment is significant with positive lift

### Requirement: Sample ratio mismatch detection
Results SHALL include a chi-square sample-ratio-mismatch test comparing exposures to the configured weights
and flag a mismatch when its p-value is below 0.001.

#### Scenario: Skewed exposures
- **WHEN** a 50/50 experiment has 1000 control exposures and 700 treatment exposures
- **THEN** the results flag a sample ratio mismatch

### Requirement: Winner selection
The results SHALL report as winner the significant variant with the best positive lift at the requested
`alpha` (default 0.05); when no variant is significantly better than control no winner is reported.

#### Scenario: Custom alpha
- **WHEN** a client requests results with `alpha=0.01` and the best variant has p-value 0.03
- **THEN** no winner is reported
