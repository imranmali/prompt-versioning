# Tasks

## 1. Prompt registry

- [x] 1.1 Add prompt schemas and service (create/list/search/tag filter/get/patch); verify `tests/test_prompts.py` registry cases pass
- [x] 1.2 Implement `/v1/prompts` CRUD routes with role checks; verify 201/409/404/422 and 403 for runtime keys

## 2. Versions

- [x] 2.1 Implement version creation with variable extraction, content hash, idempotent re-submit and conflict retry; verify version tests
- [x] 2.2 Implement version listing and `latest` alias lookup; verify pagination and 404 tests
- [x] 2.3 Implement version diff endpoint; verify diff test covers template, variables and model settings

## 3. Labels

- [x] 3.1 Implement label put/list/delete with history recording; verify label tests
- [x] 3.2 Implement label history and rollback; verify rollback and 409 tests

## 4. Rendering

- [x] 4.1 Implement `/render` by version, label or latest with strict variables; verify render tests including missing variables and sandbox violation

## Workflow follow-up

- Archive the change after the pull request is green.
