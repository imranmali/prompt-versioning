# prompt-labels Specification

## Purpose
Decouples deploying a prompt from writing it: labels such as `production` point at a version and can
be moved, audited and rolled back instantly without redeploying applications.

## Requirements

### Requirement: Assign label
Editors SHALL point a label (name matching `^[a-z0-9][a-z0-9_-]{0,63}$`) at an existing version with
`PUT /v1/prompts/{name}/labels/{label}`. Creating or moving a label MUST record a history entry with the
previous version, new version, actor and timestamp.

#### Scenario: Promote to production
- **WHEN** an editor puts label `production` on version 2
- **THEN** the label resolves to version 2 and a history entry from null to 2 is recorded

#### Scenario: Label unknown version
- **WHEN** an editor puts a label on version 42 that does not exist
- **THEN** the response status is 404

### Requirement: List and delete labels
Clients SHALL list a prompt's labels with the version each points at, and editors SHALL delete a label,
which MUST also be recorded in history.

#### Scenario: Delete label
- **WHEN** an editor calls `DELETE /v1/prompts/{name}/labels/staging`
- **THEN** the response status is 204 and the label no longer appears in the listing

### Requirement: Label history
The service SHALL return the history of a label newest first via `GET /v1/prompts/{name}/labels/{label}/history`.

#### Scenario: History after two moves
- **WHEN** `production` was moved to version 1 and then to version 2
- **THEN** the history lists the move 1→2 before the move null→1

### Requirement: Roll back label
Editors SHALL roll a label back to the version it pointed at before its most recent move via
`POST /v1/prompts/{name}/labels/{label}/rollback`. If there is no previous version the request MUST fail with 409.

#### Scenario: Rollback production
- **WHEN** `production` moved from version 1 to version 2 and an editor rolls it back
- **THEN** `production` points at version 1 and a history entry 2→1 is recorded

#### Scenario: Nothing to roll back to
- **WHEN** a label has only ever pointed at one version and an editor rolls it back
- **THEN** the response status is 409
