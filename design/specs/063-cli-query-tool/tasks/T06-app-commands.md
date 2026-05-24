---
task_id: "T06"
title: "Add app commands"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#1", "FR#2", "FR#6", "AC#1", "AC#11"]
---

## Summary

Implement the `app` command group: `app` (list all apps), `app health <key>`, `app activity <key>`, `app config <key>`, and `app source <key>`. The list subcommand uses the global manifests endpoint. Health and activity use per-app telemetry endpoints and support `--instance` filtering. Activity also supports `--since` and `--limit`.

## Prompt

### Create `src/hassette/cli/commands/app.py`

**`hassette app`** (bare) — `GET /api/apps/manifests` → `AppManifestListResponse`
- Render the `manifests` list as a table
- Each item is `AppManifestResponse` — columns: app_key, status, display_name, instance_count, and a selection of summary fields
- No filtering flags — this lists all apps

**`hassette app health <key>`** — `GET /api/telemetry/app/{key}/health` → `AppHealthResponse`
- Positional argument: `key` (app_key)
- Render as detail panel
- Supports `--instance` (optional): passes `instance_index` to the endpoint. Defaults to index 0 per the API behavior.
- Supports `--since` and `--source-tier`
- Fields: check `AppHealthResponse` in `web/models.py` line 284

**`hassette app activity <key>`** — `GET /api/telemetry/app/{key}/activity` → `list[ActivityFeedEntry]`
- Positional argument: `key`
- Render as table
- Supports `--instance` (optional): when omitted, the API returns activity across all instances (unlike other endpoints which default to 0)
- Supports `--since` and `--limit`
- Fields: check `ActivityFeedEntry` in `core/telemetry_models.py` line 281

**`hassette app config <key>`** — `GET /api/apps/{key}/config` → `AppConfigResponse`
- Positional argument: `key`
- Render as detail panel
- No filtering flags
- Fields: check `AppConfigResponse` in `web/models.py` line 466

**`hassette app source <key>`** — `GET /api/apps/{key}/source` → `AppSourceResponse`
- Positional argument: `key`
- Render as detail panel (source code display)
- No filtering flags
- Fields: check `AppSourceResponse` in `web/models.py` line 477

### Register commands

Register `app` as a subcommand group on the cyclopts App, with `health`, `activity`, `config`, `source` as sub-subcommands. The bare `app` (no sub-subcommand) lists all apps.

### Unit tests

For each subcommand, test with a mocked HTTP client:
- Bare `app` calls `GET /api/apps/manifests`
- `app health my-app` calls `GET /api/telemetry/app/my-app/health`
- `app health my-app --instance 1` passes `instance_index=1`
- `app health my-app --instance office` triggers name resolution (mock manifest response)
- `app activity my-app --since 1h --limit 10` passes correct query params
- `app activity my-app` (no `--instance`) does NOT pass instance_index (API returns all instances)
- `app config my-app` calls `GET /api/apps/my-app/config`
- `app source my-app` calls `GET /api/apps/my-app/source`
- Column definitions produce valid tables with representative data

## Focus

- Response models: `AppManifestListResponse` (models.py:131), `AppManifestResponse` (models.py:109), `AppHealthResponse` (models.py:284), `AppConfigResponse` (models.py:466), `AppSourceResponse` (models.py:477), `ActivityFeedEntry` (telemetry_models.py:281)
- Route endpoints: apps.py `GET /api/apps/manifests` (line 54), `GET /api/apps/{key}/config` (line 108), `GET /api/apps/{key}/source` (line 133); telemetry.py `GET /api/telemetry/app/{key}/health` (line 129), `GET /api/telemetry/app/{key}/activity` (line 200)
- Instance behavior difference: `activity` defaults to all instances when `instance_index` is omitted; `health` defaults to index 0. This is an API behavior, not a CLI decision.
- `AppManifestListResponse` wraps `manifests: list[AppManifestResponse]` — extract the list for table rendering
- cyclopts sub-subcommand registration: verify the exact API for nested command groups in cyclopts v4

## Verify

- [ ] FR#1: Each app subcommand queries the correct API endpoint and displays the result
- [ ] FR#2: App resources are accessible as noun-verb subcommands (app, app health, app activity, app config, app source)
- [ ] FR#6: `--instance` filters by instance index or resolved name on health and activity commands
- [ ] AC#1: All five app endpoints are queryable via CLI
- [ ] AC#11: `app health my-app --instance 1` returns instance-specific data; `--instance office` resolves name to index
