---
work_package_id: "WP01b"
title: "Web layer migration — routes, templates, DI cutover, test infrastructure"
lane: "done"
plan_section: "DI Migration + Template Updates"
depends_on: ["WP01"]
---

## Objectives & Success Criteria

All web routes and Jinja templates are migrated to the new DI aliases. `DataSyncDep` is removed. Owner map filtering is eliminated from both Python handlers and template markup. Web test infrastructure updated. Full suite passes.

- `web/dependencies.py`: `DataSyncDep` deleted; only `RuntimeDep`, `TelemetryDep`, `SchedulerDep` remain
- All files in `web/routes/` use correct new dep per design doc consumer table:
  - `apps.py`, `events.py`, `health.py`, `logs.py` → `RuntimeDep`
  - `scheduler.py` → `TelemetryDep` + `SchedulerDep`
  - `bus.py` → `TelemetryDep`
  - `ws.py` line 85: `websocket.app.state.hassette.data_sync_service` → `websocket.app.state.hassette.runtime_query_service`
- All routes/partials in `web/ui/router.py` and `web/ui/partials.py` use correct new deps per design doc table
- No `app_owner_map` or `instance_owner_map` in any route handler or template context variable
- Owner-based filtering removed from scheduler, bus, and app-detail route handlers
- The 5 Jinja template partials rewritten to use `app_key`/`instance_index` from query results instead of owner map lookups: `scheduler_jobs.html`, `scheduler_history.html`, `bus_listeners.html`, `app_detail_listeners.html`, `app_detail_jobs.html`
- `src/hassette/web/CLAUDE.md` updated: `DataSyncDep` references replaced with `RuntimeDep`, `TelemetryDep`, `SchedulerDep`
- `src/hassette/test_utils/web_mocks.py`: `create_mock_data_sync_service()` renamed/updated to `create_mock_runtime_query_service()`; `TelemetryQueryService` stub wired with empty return values for all 9 methods
- `src/hassette/test_utils/__init__.py`: re-export updated from `create_mock_data_sync_service` to `create_mock_runtime_query_service`
- `tests/e2e/conftest.py`: patch path updated from `hassette.core.data_sync_service` → `hassette.core.runtime_query_service`
- `uv run pytest -n auto` passes (bus/scheduler routes return empty data from TelemetryQueryService stubs — acceptable)
- `uv run pyright` passes

## Subtasks

1. Remove `DataSyncDep` from `web/dependencies.py` (now that new deps exist from WP01, no call sites remain once this WP completes).
2. Migrate `web/routes/` files to new deps per design doc consumer table. `apps.py`, `events.py`, `health.py`, `logs.py` → `RuntimeDep`. `scheduler.py` → `TelemetryDep` + `SchedulerDep`. `bus.py` → `TelemetryDep`. For `ws.py`: change line 85 only — `websocket.app.state.hassette.data_sync_service` → `websocket.app.state.hassette.runtime_query_service` (direct attribute access stays; only the attribute name changes).
3. Migrate `web/ui/router.py` to new deps per design doc table. Remove all calls to `get_user_app_owner_map()` and `get_instance_owner_map()`. Update scheduler, bus, and app-detail routes to call telemetry/scheduler methods directly with `app_key`/`instance_index` from the URL path. Stop passing `app_owner_map`/`instance_owner_map` as template context.
4. Migrate `web/ui/partials.py` to new deps per design doc table with the same owner map removal.
5. Update the 5 Jinja template partials that reference `app_owner_map`/`instance_owner_map`: `scheduler_jobs.html`, `scheduler_history.html`, `bus_listeners.html`, `app_detail_listeners.html`, `app_detail_jobs.html`. Rewrite any owner-lookup expressions (`app_owner_map[job.owner]`, etc.) to use `app_key`/`instance_index` columns that come directly from telemetry/scheduler query results.
6. Update `src/hassette/web/CLAUDE.md`: in "Shared Dependency Aliases" and "How to Add a New Page", replace `DataSyncDep` with `RuntimeDep`, `TelemetryDep`, `SchedulerDep`.
7. Update `src/hassette/test_utils/web_mocks.py`: rename `create_mock_data_sync_service()` to `create_mock_runtime_query_service()` (update `create_hassette_stub()` to wire `RuntimeQueryService`); add empty-return stubs for all 9 `TelemetryQueryService` methods; remove mock setup for deleted BusService/SchedulerService stub methods.
8. Update `src/hassette/test_utils/__init__.py`: update re-export from `create_mock_data_sync_service` to `create_mock_runtime_query_service`.
9. Update `tests/e2e/conftest.py`: update patch path from `hassette.core.data_sync_service` → `hassette.core.runtime_query_service`; update any `DataSyncService` type references.
10. Run `uv run pytest -n auto` and `uv run pyright`; fix failures.

## Test Strategy

**Approach**: update-existing — no new test modules.

- `tests/e2e/`: existing browser tests must pass; scheduler/bus pages render with empty data (TelemetryQueryService stubs return `[]`)
- Web route unit tests (if any): verify new deps are injected correctly
- Full suite run is the acceptance gate

## Review Guidance

Verify:
- No `DataSyncDep`, `DataSyncService`, or `data_sync_service` references remain anywhere in `src/` or `tests/` (grep to confirm)
- No `app_owner_map` or `instance_owner_map` in any route handler, template context, or Jinja template (grep to confirm)
- `ws.py` uses `hassette.runtime_query_service`, not `hassette.data_sync_service`
- Every route/partial that needs telemetry injects `TelemetryDep`; scheduler routes also inject `SchedulerDep`
- `src/hassette/web/CLAUDE.md` no longer references `DataSyncDep`
- `test_utils/__init__.py` exports `create_mock_runtime_query_service`, not `create_mock_data_sync_service`

## Activity Log
- 2026-03-14T12:31:52Z — system — lane=doing — moved from planned
- 2026-03-14T13:17:21Z — system — lane=done — moved from doing
