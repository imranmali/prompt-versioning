# Proposal: Prompt versioning

## Why

Teams iterate on LLM prompts constantly but usually keep them as string literals in application
code, so there is no history, no review trail, no way to roll back a bad prompt without a redeploy,
and no safe way to promote a prompt from staging to production. PromptLab needs a registry where
every prompt change is an immutable, diffable version and deployments are pointers (labels).

## What Changes

- Prompt registry: create, list/search, fetch and update prompt metadata.
- Immutable, sequentially numbered prompt versions with template, model settings, metadata,
  commit message, author and content hash; identical re-submissions are idempotent.
- Version diffing (template unified diff, variable and model-setting changes).
- Deployment labels (e.g. `production`, `staging`) that point at versions, with full audit history
  and one-call rollback.
- Rendering of a version or label with variables, with strict validation of missing variables.

## Capabilities

### New Capabilities
- `prompt-registry`: prompts, immutable versions and version diffs.
- `prompt-labels`: movable deployment labels, label history and rollback.
- `prompt-rendering`: rendering templates of a version or label with variables.

### Modified Capabilities
- None.

## Out of Scope

- Deleting prompts or versions (versions are immutable by design; deletion is a future change).
- Experiment-aware resolution (see `add-ab-testing`, capability `prompt-resolution`).
- Calling LLM providers; PromptLab returns rendered prompts and settings, the caller invokes the model.

## Impact

- New `/v1/prompts` API surface, services and schemas.
- Uses tables `prompts`, `prompt_versions`, `prompt_labels`, `label_events` from `add-platform-foundation`.
