# Design: A/B testing

## Context

Builds on `add-platform-foundation` (tables `experiments`, `experiment_variants`, `events`, TTL cache,
templating) and the label service of `add-prompt-versioning`.

## Goals / Non-Goals

**Goals:** stateless O(1) assignment on the hot path, statistically sound fixed-horizon analysis, idempotent
ingestion safe for client retries.

**Non-Goals:** adaptive allocation, sequential/peeking corrections, per-segment breakdowns.

## Decisions

### Hash bucketing
`bucket(x) = int(sha256(x).hexdigest()[:15], 16) % 10_000`. Traffic gate uses `bucket(f"{salt}:traffic:{subject}")
< traffic_percent * 100`; variant uses `bucket(f"{salt}:variant:{subject}")` mapped onto cumulative weights scaled
to 10,000. Separate hash inputs make the gate independent of variant choice, so changing traffic does not
reshuffle enrolled subjects between variants. The salt defaults to a random token per experiment so subjects are
not correlated across experiments. Alternatives: storing assignments (needs a write per new subject and a lookup
per request), random assignment (not sticky).

### Resolution hot path
`resolve` loads the prompt's running experiment with variants and versions through the bounded TTL cache
(`PROMPTLAB_RESOLVE_CACHE_TTL_SECONDS`, default 2s, 0 disables), then computes assignment in memory. Lifecycle
changes invalidate the local cache entry; other replicas converge within the TTL.

### Ingestion
Events are validated as a batch (unknown experiment ids → 422 for the whole batch, nothing written). Duplicate
detection: pre-select existing `event_id`s for the batch, and rely on the `UNIQUE(experiment_id, event_id)`
constraint as the final guard. Variant attribution reuses the assignment function.

### Statistics (pure Python, no SciPy)
- Binary: Wilson score interval per variant; pooled two-proportion z-test vs control; normal CDF via `math.erfc`.
- Numeric: mean/variance from `COUNT`, `SUM`, `SUM(value²)` aggregates (one GROUP BY query, no row loading);
  Welch's t-test with Welch–Satterthwaite degrees of freedom; Student-t CDF via the regularized incomplete beta
  function (Lentz continued fraction).
- SRM: Pearson chi-square goodness of fit vs weight-proportional expectation; chi-square survival via the
  regularized upper incomplete gamma function; mismatch threshold p < 0.001.
- Binary exposure denominators count distinct exposed subjects; conversions count distinct exposed subjects with
  at least one metric event in the same variant.
Rejected: SciPy (large native dependency for a handful of functions). Accuracy is pinned by unit tests against
reference values.

## Risks / Trade-offs

- [Results queries scan an experiment's events] → composite index `(experiment_id, name, variant_id)`; analytics
  can later move to a read replica or pre-aggregated rollups without API changes.
- [Peeking inflates false positives] → documented; sequential testing is out of scope.
- [Cache staleness after start/pause on other replicas] → bounded by TTL (default 2s).
