---
task_id: "T05"
title: "Add system and misc commands"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#1", "FR#2", "AC#1"]
---

## Summary

Implement the simple, single-endpoint commands that don't require filtering: `status`, `telemetry`, `dashboard`, `config`, `service`, and `event`. Each command fetches from one API endpoint, deserializes the response, and passes it to the rendering layer with command-specific column definitions. Event supports `--limit`.

## Prompt

### Create `src/hassette/cli/commands/status.py`

**`hassette status`** — `GET /api/health` → `SystemStatusResponse`
- Render as detail (key-value panel) in human mode
- Column/field selection for panel: status, websocket_connected, uptime_seconds (format as human-readable duration), entity_count, app_count, version, services_running, boot_issues (count or summary)

**`hassette telemetry`** — `GET /api/telemetry/status` → `TelemetryStatusResponse`
- Render as detail panel
- Fields: check `TelemetryStatusResponse` in `web/models.py` line 379

**`hassette dashboard`** — `GET /api/telemetry/dashboard/app-grid` → `DashboardAppGridResponse`
- Render as table (the grid contains per-app rows)
- Fields: check `DashboardAppGridResponse` in `web/models.py` line 373

### Create `src/hassette/cli/commands/misc.py`

**`hassette config`** — `GET /api/config` → `ConfigResponse`
- Render as detail panel
- Fields: check `ConfigResponse` in `web/models.py` line 449

**`hassette service`** — `GET /api/services` → `dict[str, Any]`
- Render using `render_raw()` — this is untyped HA data
- No Pydantic model — pass the raw JSON dict

**`hassette event`** — `GET /api/events/recent` → `list[EventEntry]`
- Render as table
- Accepts `--limit` flag (shared type from T02)
- No `--app` filtering — the events endpoint doesn't support it (design doc constraint)
- Fields: check `EventEntry` in `web/models.py` line 142
- Columns: select fields appropriate for an 80-column display (event_type, timestamp, key data)

### Register commands

Wire these commands into the cyclopts App in `cli/__init__.py` (or via subcommand registration). Each command module defines its cyclopts command function; `__init__.py` registers them.

### Unit tests

Use the shared mock client fixture from T03 and test data factories from `src/hassette/test_utils/web_helpers.py`. Do NOT create parallel mock client setup or test data builders.

For each command, test with the mocked HTTP client:
- Command calls the correct API endpoint
- Command passes the response model to the renderer
- `event --limit 10` passes `limit=10` as query param
- Each command's column definitions produce a valid table with representative data

## Focus

- Response models to import from `web/models.py`: `SystemStatusResponse` (line 64), `TelemetryStatusResponse` (line 379), `DashboardAppGridResponse` (line 373), `ConfigResponse` (line 449), `EventEntry` (line 142)
- Route endpoints: health.py `GET /api/health`, telemetry.py `GET /api/telemetry/status` and `GET /api/telemetry/dashboard/app-grid`, config.py `GET /api/config`, services.py `GET /api/services`, events.py `GET /api/events/recent`
- The events endpoint accepts `limit` as a query parameter — check `src/hassette/web/routes/events.py` for the exact parameter name
- `dict[str, Any]` for services — use `render_raw()` from the rendering layer, not `render_table()`
- Keep column selections tight for 80-column display. `status` is a detail view (no width concern). Tables (dashboard, event) need careful column choices.

## Verify

- [ ] FR#1: Each command queries the correct API endpoint and displays the deserialized result
- [ ] FR#2: Each API resource is accessible as a noun-based subcommand (`status`, `telemetry`, `dashboard`, `config`, `service`, `event`)
- [ ] AC#1: All six endpoints are queryable and produce correct output in both human and JSON modes
