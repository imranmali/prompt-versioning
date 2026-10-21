# Tasks

## 1. Experiment management

- [x] 1.1 Add experiment schemas and service with variant validation and control selection; verify create/validation tests
- [x] 1.2 Implement list/get/patch and lifecycle transitions with single-running guard; verify lifecycle tests
- [x] 1.3 Implement complete with winner promotion through the label service; verify promotion test

## 2. Assignment

- [x] 2.1 Implement hash bucketing with traffic gate and weighted selection; verify determinism and distribution tests
- [x] 2.2 Implement `POST /v1/experiments/{id}/assign`; verify enrolled/not-enrolled API tests

## 3. Analytics

- [ ] 3.1 Implement statistics module (Wilson, z-test, Welch t-test, chi-square SRM); verify against reference values
- [ ] 3.2 Implement batched idempotent event ingestion with variant attribution; verify ingestion tests
- [ ] 3.3 Implement results endpoint for binary and numeric metrics with winner selection; verify results tests

## 4. Resolution

- [ ] 4.1 Implement `POST /v1/prompts/{name}/resolve` with cache, fallback label, exposure recording and rendering; verify resolve tests

## Workflow follow-up

- Archive the change after the pull request is green.
