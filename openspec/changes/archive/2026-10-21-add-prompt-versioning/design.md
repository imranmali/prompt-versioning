# Design: Prompt versioning

## Context

Builds on the schema and template engine from `add-platform-foundation` (`prompts`, `prompt_versions`,
`prompt_labels`, `label_events`, `services/templating.py`).

## Goals / Non-Goals

**Goals:** immutable history, race-free version numbering, cheap label moves, auditable deployments.

**Non-Goals:** branching/merging of prompt versions, semantic versioning, prompt deletion.

## Decisions

- **Integer versions per prompt** (1, 2, 3…) rather than semver: monotonic, trivially comparable, maps to
  "commit" semantics. Next number = `max(version)+1` inside the transaction; the `UNIQUE(prompt_id, version)`
  constraint catches concurrent writers and the service retries a bounded number of times on `IntegrityError`.
- **Content hash** = SHA-256 of canonical JSON of `{template, model_settings}` (sorted keys). Used for the
  idempotent re-submit check against the latest version only, so reverting to an older text still creates a
  new version (history stays linear and truthful).
- **Labels are rows, history is append-only** (`label_events`). Rollback reads the newest event for the label
  and moves to its `from_version`; the rollback itself is recorded, so repeated rollbacks toggle.
- **Diff** uses `difflib.unified_diff` on templates (`fromfile=vA`, `tofile=vB`) and set/dict comparison for
  variables and model settings. Alternative: return both versions and diff client-side — rejected, a
  server-side diff gives consistent review output for UIs and CI bots.
- **Prompt summary** (`latest_version`, `labels`) is computed with aggregate queries rather than stored
  counters to avoid write contention.

## Risks / Trade-offs

- [Retry loop on version conflicts could spin under extreme contention] → bounded to 5 attempts then 409.
- [Offset pagination degrades on huge version lists] → acceptable for prompt-scale data; index on
  `(prompt_id, version)` keeps it fast.
