# prompt-rendering Specification

## Purpose
Turns a stored prompt template into the final text sent to an LLM, safely and with strict variable
checking, so applications never ship half-filled prompts.

## Requirements

### Requirement: Render prompt
Clients SHALL render a prompt with `POST /v1/prompts/{name}/render` providing `variables` and at most one
of `version` or `label`; when neither is given the latest version is rendered. The response MUST include the
rendered text, the version number and the model settings.

#### Scenario: Render by label
- **WHEN** `production` points at version 2 with template `Hi {{ name }}` and a client renders label `production` with `{"name": "Ada"}`
- **THEN** the rendered text is `Hi Ada` and the version is 2

#### Scenario: Both version and label
- **WHEN** a client supplies both `version` and `label`
- **THEN** the response status is 422

### Requirement: Strict variables
Rendering MUST fail with 422 `missing_variables` listing every missing variable when required variables
are not supplied.

#### Scenario: Missing variable
- **WHEN** a client renders `Hi {{ name }} from {{ city }}` with only `name`
- **THEN** the response status is 422, the code is `missing_variables` and details list `city`

### Requirement: Sandboxed rendering
Templates SHALL be rendered in a sandbox that prevents access to unsafe attributes; violations MUST fail
with 422 `invalid_template` and never execute arbitrary code.

#### Scenario: Unsafe attribute access
- **WHEN** a template contains `{{ name.__class__.__mro__ }}`
- **THEN** rendering fails with code `invalid_template`
