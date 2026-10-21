# Prompts API guide

PromptLab stores every change to a prompt as an **immutable, numbered version** and deploys
versions through movable **labels** such as `production` or `staging`. Applications fetch or
render a prompt by label, so promoting or rolling back a prompt never needs a redeploy.

All endpoints live under `/v1/prompts` and need an API key, sent as `X-API-Key: <key>` or
`Authorization: Bearer <key>`.

| Operation                                   | Minimum role |
|---------------------------------------------|--------------|
| List, fetch, browse versions, diff, history | `runtime`    |
| Render                                      | `runtime`    |
| Create or update prompts, create versions   | `editor`     |
| Assign, delete or roll back labels          | `editor`     |

The examples below assume:

```bash
export PL=http://localhost:8000/v1
export KEY=pl_xxx   # an editor key
```

Errors always use the same envelope:

```json
{"error": {"code": "not_found", "message": "Prompt 'x' not found", "details": null, "request_id": "..."}}
```

Common codes: `validation_error` (422), `invalid_template` (422), `missing_variables` (422),
`not_found` (404), `conflict` (409), `forbidden` (403), `unauthorized` (401).

## Prompts

### Create a prompt

```bash
curl -s -X POST "$PL/prompts" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"name": "support-reply", "description": "Replies to support tickets", "tags": ["support"]}'
```

Returns `201`:

```json
{
  "id": "6f1c...",
  "name": "support-reply",
  "description": "Replies to support tickets",
  "tags": ["support"],
  "latest_version": null,
  "labels": {},
  "created_at": "2026-10-20T12:00:00Z",
  "updated_at": "2026-10-20T12:00:00Z"
}
```

- `name` must match `^[a-z0-9][a-z0-9._-]{0,127}$` and is unique (`409 conflict` otherwise).
  Names cannot be changed later.
- `tags`: up to 32 non-empty strings of at most 64 characters; duplicates are dropped while
  preserving order.

### List and search

```bash
curl -s "$PL/prompts?limit=20&offset=0" -H "X-API-Key: $KEY"
curl -s "$PL/prompts?search=support" -H "X-API-Key: $KEY"   # name or description, case-insensitive
curl -s "$PL/prompts?tag=support" -H "X-API-Key: $KEY"      # exact tag match
```

Results are ordered by name and paginated (`limit` 1–200, default 50):

```json
{"items": [ ... ], "total": 3, "limit": 20, "offset": 0}
```

The tag filter runs in the database (JSONB containment on PostgreSQL, `json_each` on SQLite), so
`total` always reflects the filtered set.

### Fetch a prompt

```bash
curl -s "$PL/prompts/support-reply" -H "X-API-Key: $KEY"
```

The response includes `latest_version` (or `null`) and `labels`, a map of label name to the
version number it points at, e.g. `{"production": 2, "staging": 3}`.

### Update description or tags

```bash
curl -s -X PATCH "$PL/prompts/support-reply" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"tags": ["support", "email"]}'
```

Omitted (or `null`) fields are left unchanged. Versions are never affected.

## Versions

### Create a version

```bash
curl -s -X POST "$PL/prompts/support-reply/versions" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{
        "template": "Hello {{ name }}, thanks for asking about {{ topic }}.",
        "model_settings": {"model": "gpt-4o", "temperature": 0.2},
        "metadata": {"ticket": "PL-42"},
        "commit_message": "Friendlier greeting"
      }'
```

Returns `201`:

```json
{
  "id": "9a0e...",
  "prompt": "support-reply",
  "version": 1,
  "template": "Hello {{ name }}, thanks for asking about {{ topic }}.",
  "variables": ["name", "topic"],
  "model_settings": {"model": "gpt-4o", "temperature": 0.2},
  "metadata": {"ticket": "PL-42"},
  "commit_message": "Friendlier greeting",
  "content_hash": "3b9f...",
  "created_by": "ci-editor",
  "created_at": "2026-10-20T12:01:00Z"
}
```

- Templates are [Jinja2](https://jinja.palletsprojects.com/) (1 to 100,000 characters). A template
  that does not parse is rejected with `422 invalid_template`.
- `variables` are extracted from the template automatically.
- `created_by` is the name of the API key that made the request.
- Versions are numbered 1, 2, 3, ... per prompt. Concurrent writers never get the same number.
- Versions are immutable: there is no endpoint to edit or delete them.

**Idempotent re-submission.** `content_hash` is the SHA-256 of the canonical JSON of
`{"template", "model_settings"}`. If you submit the same template and model settings as the
**latest** version, nothing is created and the latest version is returned with `200`. This makes
it safe to "sync" prompts from CI on every build. Reverting to the text of an *older* version
does create a new version, so the history stays linear.

### Browse versions

```bash
curl -s "$PL/prompts/support-reply/versions?limit=10" -H "X-API-Key: $KEY"   # newest first
curl -s "$PL/prompts/support-reply/versions/3" -H "X-API-Key: $KEY"
curl -s "$PL/prompts/support-reply/versions/latest" -H "X-API-Key: $KEY"
```

An unknown version number yields `404`; a reference that is neither a number nor `latest` yields `422`.

### Diff two versions

```bash
curl -s "$PL/prompts/support-reply/diff?from=1&to=latest" -H "X-API-Key: $KEY"
```

```json
{
  "prompt": "support-reply",
  "from_version": 1,
  "to_version": 2,
  "template_diff": "--- v1\n+++ v2\n@@ -1 +1 @@\n-Hi {{ name }}\n+Hello {{ name }} {{ title }}",
  "variables": {"added": ["title"], "removed": []},
  "model_settings": {
    "added": {"max_tokens": 256},
    "removed": {},
    "changed": {"temperature": {"from": 0.2, "to": 0.7}}
  }
}
```

`template_diff` is a standard unified diff (empty when the templates are identical).

## Labels

A label is a named pointer to a version. Label names match `^[a-z0-9][a-z0-9_-]{0,63}$`.

### Assign or move a label

```bash
curl -s -X PUT "$PL/prompts/support-reply/labels/production" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"version": 2}'
```

```json
{"name": "production", "version": 2, "updated_by": "ci-editor", "updated_at": "2026-10-20T12:05:00Z"}
```

The label is created if needed. Pointing at a version that does not exist yields `404`. Every
change is recorded in the label's history; putting a label on the version it already points at
is a no-op.

### List and delete labels

```bash
curl -s "$PL/prompts/support-reply/labels" -H "X-API-Key: $KEY"
curl -s -X DELETE "$PL/prompts/support-reply/labels/staging" -H "X-API-Key: $KEY"   # 204
```

Deleting an absent label yields `404`. Deletions are recorded in history (`to_version: null`).

### History

```bash
curl -s "$PL/prompts/support-reply/labels/production/history?limit=20" -H "X-API-Key: $KEY"
```

Newest first, paginated:

```json
{
  "items": [
    {"label": "production", "from_version": 1, "to_version": 2, "actor": "ci-editor", "created_at": "..."},
    {"label": "production", "from_version": null, "to_version": 1, "actor": "alice", "created_at": "..."}
  ],
  "total": 2, "limit": 20, "offset": 0
}
```

A label that never existed has an empty history.

### Roll back

```bash
curl -s -X POST "$PL/prompts/support-reply/labels/production/rollback" -H "X-API-Key: $KEY"
```

Moves the label back to the version it pointed at before its most recent move and records the
rollback in history, so a second rollback undoes the first. Returns `409 conflict` when the label
does not exist or has no previous version (for example it has only ever pointed at one version).

## Rendering

```bash
curl -s -X POST "$PL/prompts/support-reply/render" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"label": "production", "variables": {"name": "Ada", "topic": "billing"}}'
```

```json
{
  "prompt": "support-reply",
  "version": 2,
  "label": "production",
  "rendered": "Hello Ada, thanks for asking about billing.",
  "model_settings": {"model": "gpt-4o", "temperature": 0.2}
}
```

- Pass at most one of `version` (a number) or `label`; passing both yields `422`. With neither,
  the latest version is rendered (`404` if the prompt has no versions).
- Variables are strict: if any are missing the request fails with `422 missing_variables` and
  `details.missing` lists all of them. Extra variables are ignored.
- Templates run in a Jinja2 sandbox. Access to unsafe attributes such as
  `{{ name.__class__.__mro__ }}` fails with `422 invalid_template`.

PromptLab does not call the model: pass `rendered` and `model_settings` to your LLM client.

## Typical workflow

```bash
# 1. CI syncs the prompt on every build (idempotent).
curl -s -X POST "$PL/prompts/support-reply/versions" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d @support-reply.json

# 2. Review the change.
curl -s "$PL/prompts/support-reply/diff?from=2&to=latest" -H "X-API-Key: $KEY"

# 3. Promote to staging, then production.
curl -s -X PUT "$PL/prompts/support-reply/labels/staging" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"version": 3}'
curl -s -X PUT "$PL/prompts/support-reply/labels/production" -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d '{"version": 3}'

# 4. Something went wrong? Roll back instantly.
curl -s -X POST "$PL/prompts/support-reply/labels/production/rollback" -H "X-API-Key: $KEY"
```
