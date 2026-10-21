# api-access-control Specification

## Purpose
Controls who may call the PromptLab API by authenticating callers with API keys and
authorizing each operation against a hierarchical role.

## Requirements

### Requirement: API key authentication
Every `/v1` endpoint SHALL require a valid, non-revoked API key supplied either in the
`X-API-Key` header or as an `Authorization: Bearer <key>` header. Requests without a valid key
MUST be rejected with HTTP 401 and error code `unauthorized`.

#### Scenario: Missing key
- **WHEN** a client calls `GET /v1/prompts` without credentials
- **THEN** the response status is 401 and the error code is `unauthorized`

#### Scenario: Revoked key
- **WHEN** a client calls a `/v1` endpoint with a key that has been revoked
- **THEN** the response status is 401

#### Scenario: Bearer token accepted
- **WHEN** a client sends a valid key as `Authorization: Bearer <key>`
- **THEN** the request is authenticated

### Requirement: Hierarchical roles
Each API key SHALL have exactly one role: `runtime`, `editor` or `admin`, where each role
includes every permission of the roles before it. `runtime` MAY read resources, resolve and
render prompts and ingest events; `editor` MAY also create and change prompts, labels and
experiments; `admin` MAY also manage API keys. Insufficient role MUST yield HTTP 403 with code `forbidden`.

#### Scenario: Runtime key cannot create prompts
- **WHEN** a `runtime` key calls `POST /v1/prompts`
- **THEN** the response status is 403 and the error code is `forbidden`

#### Scenario: Admin inherits editor permissions
- **WHEN** an `admin` key calls `POST /v1/prompts` with a valid body
- **THEN** the prompt is created

### Requirement: Bootstrap administrator key
The service SHALL accept the key configured in `PROMPTLAB_BOOTSTRAP_ADMIN_KEY` as an `admin`
key so that the first real keys can be issued. When the variable is unset no bootstrap key exists.

#### Scenario: Bootstrap key issues the first key
- **WHEN** an operator calls `POST /v1/api-keys` with the bootstrap key
- **THEN** a new key is created and returned

### Requirement: API key lifecycle management
Admins SHALL be able to create, list and revoke API keys. The plaintext key MUST be returned
only once at creation; the service MUST store only a one-way hash and a short display prefix.

#### Scenario: Create key
- **WHEN** an admin calls `POST /v1/api-keys` with a name and role
- **THEN** the response status is 201 and contains the plaintext key, its id, prefix and role

#### Scenario: List keys never exposes secrets
- **WHEN** an admin calls `GET /v1/api-keys`
- **THEN** each item contains id, name, prefix, role and timestamps but no plaintext key or hash

#### Scenario: Revoke key
- **WHEN** an admin calls `DELETE /v1/api-keys/{id}`
- **THEN** the response status is 204 and later requests using that key receive 401
