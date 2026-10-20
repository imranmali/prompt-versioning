# Spec Delta

## Purpose

Gives operators and orchestrators the endpoints, error contract and telemetry needed to run
PromptLab reliably as a horizontally scaled, stateless service.

## ADDED Requirements

### Requirement: Liveness endpoint
The service SHALL expose an unauthenticated `GET /healthz` that returns HTTP 200 with
`{"status": "ok"}` whenever the process is able to serve requests, without touching the database.

#### Scenario: Process alive
- **WHEN** a probe calls `GET /healthz`
- **THEN** the response status is 200 and the body status is `ok`

### Requirement: Readiness endpoint
The service SHALL expose an unauthenticated `GET /readyz` that verifies database connectivity
and returns HTTP 200 when ready or HTTP 503 with status `unavailable` when the database cannot be reached.

#### Scenario: Database reachable
- **WHEN** a probe calls `GET /readyz` and the database is reachable
- **THEN** the response status is 200 and the body reports the database check as `ok`

#### Scenario: Database unreachable
- **WHEN** a probe calls `GET /readyz` and the database query fails
- **THEN** the response status is 503

### Requirement: Prometheus metrics
The service SHALL expose `GET /metrics` in Prometheus text format including request counts and
latency histograms labelled by method, route template and status code. Metrics MUST be disableable
via `PROMPTLAB_METRICS_ENABLED=false`.

#### Scenario: Request metrics recorded
- **WHEN** a client calls `GET /healthz` and then `GET /metrics`
- **THEN** the metrics body contains a request counter sample for the `/healthz` route

### Requirement: Uniform error envelope
All error responses SHALL use the body `{"error": {"code", "message", "details", "request_id"}}`
with a stable machine-readable `code` (e.g. `validation_error`, `not_found`, `conflict`,
`unauthorized`, `forbidden`, `internal_error`).

#### Scenario: Validation failure
- **WHEN** a client sends a request body that fails validation
- **THEN** the response status is 422 and the error code is `validation_error` with field details

#### Scenario: Unknown route
- **WHEN** a client calls a path that does not exist
- **THEN** the response status is 404 and the error code is `not_found`

#### Scenario: Unexpected failure
- **WHEN** an unhandled exception occurs while serving a request
- **THEN** the response status is 500, the error code is `internal_error` and no stack trace is returned

### Requirement: Request correlation
Every response SHALL carry an `X-Request-ID` header. When the client supplies a well-formed
`X-Request-ID` it MUST be echoed; otherwise a new identifier MUST be generated and also included in logs.

#### Scenario: Client supplied request id
- **WHEN** a client sends `X-Request-ID: abc-123`
- **THEN** the response carries `X-Request-ID: abc-123`

#### Scenario: Generated request id
- **WHEN** a client sends no request id
- **THEN** the response carries a non-empty generated `X-Request-ID`
