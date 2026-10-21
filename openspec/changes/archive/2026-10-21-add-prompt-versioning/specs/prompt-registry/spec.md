# Spec Delta

## Purpose

Stores prompts and their complete, immutable version history so every change to a prompt is
traceable, comparable and reproducible.

## ADDED Requirements

### Requirement: Create prompt
Editors SHALL be able to create a prompt with a unique `name` matching `^[a-z0-9][a-z0-9._-]{0,127}$`,
an optional description and optional tags. Creating a prompt whose name already exists MUST fail with 409 `conflict`.

#### Scenario: Prompt created
- **WHEN** an editor calls `POST /v1/prompts` with `{"name": "support-reply", "tags": ["support"]}`
- **THEN** the response status is 201 and the body contains the prompt with `latest_version` null

#### Scenario: Duplicate name rejected
- **WHEN** an editor creates a prompt with a name that already exists
- **THEN** the response status is 409 and the error code is `conflict`

#### Scenario: Invalid name rejected
- **WHEN** an editor creates a prompt named `Bad Name!`
- **THEN** the response status is 422

### Requirement: List and fetch prompts
The service SHALL list prompts with `limit`/`offset` pagination, an optional case-insensitive `search`
on name/description and an optional `tag` filter, and SHALL fetch a single prompt by name including its
latest version number and current labels. Unknown names MUST yield 404 `not_found`.

#### Scenario: Paginated listing
- **WHEN** a client calls `GET /v1/prompts?limit=2&offset=0` with three prompts stored
- **THEN** the body contains two items and `total` equal to 3

#### Scenario: Filter by tag
- **WHEN** a client calls `GET /v1/prompts?tag=support`
- **THEN** only prompts carrying the `support` tag are returned

#### Scenario: Unknown prompt
- **WHEN** a client calls `GET /v1/prompts/does-not-exist`
- **THEN** the response status is 404

### Requirement: Update prompt metadata
Editors SHALL be able to update a prompt's description and tags with `PATCH /v1/prompts/{name}`.
The name and version history MUST NOT change.

#### Scenario: Update tags
- **WHEN** an editor patches a prompt with `{"tags": ["a", "b"]}`
- **THEN** the prompt's tags are `["a", "b"]` and its versions are unchanged

### Requirement: Immutable sequential versions
Creating a version SHALL assign the next integer version number (starting at 1) and store the template,
declared variables, model settings, metadata, commit message, author key name and a content hash.
Versions MUST NOT be modifiable after creation. Concurrent creations MUST never produce duplicate numbers.

#### Scenario: First version
- **WHEN** an editor calls `POST /v1/prompts/support-reply/versions` with a template
- **THEN** the response status is 201 and the version number is 1

#### Scenario: Variables extracted
- **WHEN** a version is created with template `Hello {{ name }}, about {{ topic }}`
- **THEN** the stored variables are `["name", "topic"]`

#### Scenario: Invalid template
- **WHEN** a version is created with template `Hello {{ name`
- **THEN** the response status is 422 and the error code is `invalid_template`

### Requirement: Idempotent version creation
When a submitted template and model settings are identical to the latest version's, the service SHALL
return the existing latest version with status 200 instead of creating a new version.

#### Scenario: Re-submitting identical content
- **WHEN** an editor submits exactly the same template and model settings as version 3, the latest version
- **THEN** the response status is 200, the version number is 3 and no version 4 exists

### Requirement: Browse versions
Clients SHALL list a prompt's versions newest first with pagination and fetch a single version by number
or by the alias `latest`.

#### Scenario: Fetch latest alias
- **WHEN** a client calls `GET /v1/prompts/support-reply/versions/latest` and versions 1..3 exist
- **THEN** version 3 is returned

#### Scenario: Unknown version
- **WHEN** a client fetches version 99 of a prompt with three versions
- **THEN** the response status is 404

### Requirement: Diff versions
The service SHALL compare two versions of a prompt via `GET /v1/prompts/{name}/diff?from=A&to=B` and return
a unified diff of the templates, added and removed variables, and added, removed and changed model settings.

#### Scenario: Diff two versions
- **WHEN** version 1 has template `Hi {{ name }}` and version 2 has `Hello {{ name }} {{ title }}`
- **THEN** the diff contains a unified template diff and lists `title` as an added variable
