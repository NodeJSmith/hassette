# Design: Decompose DataSyncService (Issue #267)

**Status:** implemented
**Spec directory**: `design/specs/004-decompose-datasyncservice/`
**Issue**: [#267 — Decompose DataSyncService into TelemetryQueryService and RuntimeQueryService](https://github.com/NodeJSmith/hassette/issues/267)
**Research**: `design/research/2026-02-16-sqlite-command-pattern/prereq-04-frontend-query-requirements.md`, `prereq-08-datasyncservice-decomposition.md`

---

## Problem

`DataSyncService` is a monolithic facade mixing two fundamentally different data sources:

- **Historical telemetry** — listener metrics, job execution history — currently backed by in-memory stores (`BusService._listener_metrics`, `SchedulerService._execution_log`) that are now stubs with `# TODO(#267)` comments, waiting for DB-backed replacements.
- **Live runtime state** — app status, recent events, recent logs, system status, WebSocket broadcast — instant in-memory reads.

The PR #329 (CommandExecutor) installed the DB infrastructure and added stub returns everywhere the old in-memory stores were referenced. Those stubs all point to this issue. The facade must be split to:

1. Surface real telemetry from the DB via a new `TelemetryQueryService`.
2. Slim `DataSyncService` down to runtime-only state and rename it `RuntimeQueryService`.
3. Clean up dead code: entity routes, owner-mapping methods, retired scheduler accessors.
4. Replace the single `DataSyncDep` with three focused DI aliases across all web routes.

---

## Architecture

### Two services, one boundary

| Service | Renamed from | Data source | Characteristics |
|---------|-------------|-------------|-----------------|
| `RuntimeQueryService` | `DataSyncService` | In-memory (AppHandler, event buffer, log buffer, WS clients) | Instant reads, live state |
| `TelemetryQueryService` | *(new)* | `DatabaseService` (SQLite) | Async I/O, historical data, SQL queries |

Both extend `Resource`. `TelemetryQueryService` depends on `DatabaseService` for the `aiosqlite` connection. `RuntimeQueryService` keeps the same in-memory dependencies it has today.

### File layout

```
src/hassette/core/
    runtime_query_service.py    # renamed from data_sync_service.py (slimmed)
    telemetry_query_service.py  # new — DB-backed query methods
    data_sync_service.py        # DELETED
```

### DI aliases (`web/dependencies.py`)

```python
TelemetryDep = Annotated["TelemetryQueryService", Depends(get_telemetry)]
RuntimeDep   = Annotated["RuntimeQueryService",   Depends(get_runtime)]
SchedulerDep = Annotated["SchedulerService",      Depends(get_scheduler)]
# DataSyncDep — DELETED, no compat shim
```

### Hassette wiring (`core/core.py`)

```python
self._runtime_query_service  = self.add_child(RuntimeQueryService)
self._telemetry_query_service = self.add_child(TelemetryQueryService)
# _data_sync_service removed
```

Both services registered as children. `TelemetryQueryService` needs `DatabaseService` ready before it initializes (same `wait_for_ready` pattern as existing services).

---

## RuntimeQueryService — what stays, what goes

### Kept (verbatim or trivially renamed)

| Method | Notes |
|--------|-------|
| `get_app_status_snapshot()` | Unchanged |
| `get_all_manifests_snapshot()` | Unchanged |
| `get_recent_events(limit=)` | Unchanged |
| `get_recent_logs(limit=, app_key=, level=)` | Unchanged |
| `get_system_status()` | Unchanged |
| `register_ws_client()` | Unchanged |
| `unregister_ws_client(queue)` | Unchanged |
| `broadcast(message)` | Unchanged |
| `on_initialize()` / `on_shutdown()` | Unchanged |
| `_event_buffer`, `_ws_clients`, `_lock`, `_start_time` | Unchanged |

### Dropped (deleted entirely)

| Method | Reason |
|--------|--------|
| `get_entity_state()` | Entity page removed |
| `get_all_entity_states()` | Entity page removed |
| `get_domain_states()` | Entity page removed |
| `get_listener_metrics()` | → `TelemetryQueryService` |
| `get_listener_metrics_for_instance()` | → `TelemetryQueryService` |
| `get_bus_metrics_summary()` | → `TelemetryQueryService` |
| `get_job_execution_history()` | → `TelemetryQueryService` |
| `get_scheduled_jobs()` | Routes inject `SchedulerService` directly |
| `get_scheduled_jobs_for_instance()` | Routes inject `SchedulerService` directly |
| `get_scheduler_summary()` | Routes inject `SchedulerService` directly |
| `get_user_app_owner_map()` | Owner translation no longer needed |
| `get_instance_owner_map()` | Owner translation no longer needed |
| `_resolve_owner_ids()` | Internal helper, only used by dropped methods |
| `_resolve_instance_owner_id()` | Internal helper, only used by dropped methods |
| `_serialize_job()` | Only used by dropped scheduler methods |

---

## TelemetryQueryService — new methods

All queries use `app_key` + `instance_index` as the natural key (DB columns on parent tables). No owner translation. Session scoping via optional `session_id: int | None = None` parameter.

### Methods (from prereq 4)

| Method | Prereq 4 section | Replaces |
|--------|-----------------|---------|
| `get_listener_summary(app_key, instance_index, session_id=None)` | §1 | `get_listener_metrics()` + `get_listener_metrics_for_instance()` |
| `get_job_summary(app_key, instance_index, session_id=None)` | §2 | `get_job_execution_history()` |
| `get_global_summary(session_id=None)` | §3 | `get_bus_metrics_summary()` |
| `get_handler_invocations(listener_id, limit=50)` | §4 | NEW |
| `get_job_executions(job_id, limit=50)` | §5 | NEW |
| `get_recent_errors(since_ts, limit=50, session_id=None)` | §6 | NEW |
| `get_slow_handlers(threshold_ms, limit=50)` | §7 | NEW |
| `get_session_list(limit=20)` | §8 | NEW |
| `get_current_session_summary()` | §9 | NEW |

SQL queries for all methods are fully specified in `prereq-04-frontend-query-requirements.md`. The design doc does not repeat them — implementers should read the prereq directly.

### Initialization

```python
async def on_initialize(self) -> None:
    if not self.hassette.config.run_web_api:
        self.mark_ready(reason="Web API disabled")
        return
    await self.hassette.wait_for_ready([self.hassette.database_service])
    self.mark_ready(reason="TelemetryQueryService initialized")
```

Uses `self.hassette.database_service.db` (the `aiosqlite.Connection` exposed by `DatabaseService`) for all queries.

---

## Route migration

### API routes (`web/routes/`)

| File | Old dep | New dep(s) | Action |
|------|---------|-----------|--------|
| `apps.py` | `DataSyncDep` | `RuntimeDep` | Update import + sig |
| `entities.py` | `DataSyncDep` | — | **Delete file** |
| `scheduler.py` | `DataSyncDep` | `TelemetryDep` + `SchedulerDep` | Update |
| `bus.py` | `DataSyncDep` | `TelemetryDep` | Update |
| `events.py` | `DataSyncDep` | `RuntimeDep` | Update |
| `health.py` | `DataSyncDep` | `RuntimeDep` | Update |
| `logs.py` | `DataSyncDep` | `RuntimeDep` | Update |
| `ws.py` | `.data_sync_service` (direct attr) | `.runtime_query_service` (direct attr) | Update line 85 only |

Entity route registration in the router must also be removed.

### UI pages (`web/ui/router.py`)

| Route | New dep(s) |
|-------|-----------|
| `/` (dashboard) | `RuntimeDep` |
| `/apps` | `RuntimeDep` |
| `/logs` | `RuntimeDep` |
| `/scheduler` | `TelemetryDep` + `SchedulerDep` |
| `/bus` | `TelemetryDep` |
| `/apps/{app_key}` | `RuntimeDep` + `TelemetryDep` + `SchedulerDep` |
| `/apps/{app_key}/{index}` | `RuntimeDep` + `TelemetryDep` + `SchedulerDep` |

### UI partials (`web/ui/partials.py`)

| Partial | New dep(s) |
|---------|-----------|
| `app-list`, `app-row/{app_key}`, `manifest-list`, `manifest-row/{app_key}`, `instance-row/{app_key}/{index}`, `dashboard-*`, `log-entries`, `alert-failed-apps` | `RuntimeDep` |
| `bus-listeners`, `app-detail-listeners/{app_key}`, `instance-listeners/{app_key}/{index}` | `TelemetryDep` |
| `scheduler-history` | `TelemetryDep` |
| `scheduler-jobs`, `app-detail-jobs/{app_key}`, `instance-jobs/{app_key}/{index}` | `TelemetryDep` + `SchedulerDep` |

### Owner map elimination

Routes currently call `get_user_app_owner_map()` and `get_instance_owner_map()` to translate `owner_id` values (from `BusService`/`SchedulerService`) into `app_key` strings, then filter results and pass both maps as template context. After migration this pattern is removed entirely:

- **Scheduler routes/partials** (`/scheduler`, `scheduler-jobs`, `scheduler-history`): the `[j for j in all_jobs if j["owner"] in app_owner_map]` filter is deleted. `SchedulerDep` returns `app_key`-aware objects; `TelemetryDep.get_job_summary()` already queries by `app_key`/`instance_index`. No owner map needed.
- **Bus routes/partials** (`/bus`, `bus-listeners`): the `[x for x in all_listeners if x["owner"] in app_owner_map]` filter is deleted. `TelemetryDep.get_listener_summary()` queries by `app_key`/`instance_index` directly.
- **App/instance detail routes** (`/apps/{app_key}`, `/apps/{app_key}/{index}`, `app-detail-*` partials): the `owner_id` gate is removed. Routes call telemetry and scheduler methods directly with `app_key` and `instance_index` from the URL path.
- Templates stop receiving `app_owner_map` and `instance_owner_map` as context variables. All telemetry results carry `app_key`/`instance_index` columns directly.

### `web/ui/CLAUDE.md`

The "Shared Dependency Aliases" and "How to Add a New Page" sections reference `DataSyncDep`. Update both to list `RuntimeDep`, `TelemetryDep`, and `SchedulerDep` as the replacement aliases.

### `web/ui/context.py`

`alert_context()` currently accepts `DataSyncService`. Change signature to accept `RuntimeQueryService`.

---

## Test infrastructure

### `tests/unit/core/test_data_sync_service.py`

Rename to `test_runtime_query_service.py`. Remove tests for dropped methods (entity state, listener metrics, scheduler methods, owner maps). Keep tests for: `get_app_status_snapshot`, `get_all_manifests_snapshot`, `get_recent_events`, `get_recent_logs`, `get_system_status`, WS client management. Update all `DataSyncService` references to `RuntimeQueryService`.

### `tests/unit/core/test_web_ui_watcher.py`

Update `hassette.data_sync_service` → `hassette.runtime_query_service` (2 lines).

### `tests/e2e/conftest.py`

Update `create_mock_data_sync_service` → `create_mock_runtime_query_service` (or keep the helper name but update internals). Patch path changes from `hassette.core.data_sync_service` → `hassette.core.runtime_query_service`.

### `src/hassette/test_utils/web_mocks.py`

Update `create_hassette_stub()` and `create_mock_data_sync_service()` to wire `RuntimeQueryService` instead of `DataSyncService`. Add `create_mock_telemetry_query_service()` stub returning empty results (all new telemetry methods return `[]` or `None`).

### New: `tests/integration/test_telemetry_query_service.py`

Integration tests against real in-memory SQLite (same pattern as `test_command_executor.py`):
- `get_listener_summary` returns correct aggregates for seeded records
- `get_job_summary` returns correct aggregates
- `get_global_summary` returns correct totals
- `get_handler_invocations` returns ordered results, respects limit
- `get_job_executions` returns ordered results, respects limit
- `get_recent_errors` filters correctly by status
- `get_session_list` returns sessions ordered by start time
- `get_current_session_summary` returns counts for the running session

---

## Decisions and constraints

### Migration strategy: rename first, then extract

Per prereq 8's implementation note: rename `DataSyncService` → `RuntimeQueryService` (removing dropped methods) as the first commit, then add `TelemetryQueryService` in subsequent work. This keeps diffs reviewable and avoids a big-bang change.

### No compatibility shim

`DataSyncDep` is deleted. No `DataSyncDep = RuntimeDep` alias. All call sites are updated in this PR.

### Dead code deletion

The `CommandExecutor` (PR #329) already populates the DB: `listeners`, `scheduled_jobs`, `handler_invocations`, and `job_executions` tables are written by `CommandExecutor` during registration and execution. `TelemetryQueryService` reads directly from those tables — the old in-memory accessors are no longer needed.

Delete these methods as part of this PR:

**`BusService`:**
- `get_all_listener_metrics()` — returns `[]` stub, caller (`DataSyncService.get_listener_metrics()`) is being deleted
- `get_listener_metrics_by_owner()` — returns `[]` stub, caller (`DataSyncService.get_listener_metrics_for_instance()`) is being deleted

**`SchedulerService`:**
- `get_execution_history()` — returns `[]` stub, caller (`DataSyncService.get_job_execution_history()`) is being deleted; `TelemetryQueryService.get_job_summary()` queries the DB directly

Any tests covering these stub methods should also be deleted.

### `web/routes/entities.py` deletion

File deleted, its router registration removed from wherever entities routes are included. Any sidebar nav link to entities (if present) removed from `templates/components/nav.html`.

### Session scoping deferred

The session-scoped query variants (optional `session_id` parameter) are implemented in `TelemetryQueryService` methods per the method signatures above, but the UI toggle ("current session" vs "all time") is tracked in issue #268 and not surfaced in this PR. The backend plumbing ships here; the UI control ships later.

---

## Out of scope (→ #268)

- `on_error`/`on_exception` hooks on `CommandExecutor`
- Session heartbeat loop
- Retention cleanup loop
- Size failsafe
- Handler invocation drill-down UI
- Session list UI
- Current session vs all-time toggle UI
- Source code display in UI

---

## Acceptance criteria

All items from issue #267:

- [ ] `DataSyncService` renamed to `RuntimeQueryService`, dropped methods removed
- [ ] `TelemetryQueryService` created with all query methods from prereq 4 (§1–9)
- [ ] All queries use `app_key`/`instance_index` directly (no owner translation)
- [ ] Session-scoped query variants via optional `session_id` parameter
- [ ] `DataSyncDep` replaced with `TelemetryDep`, `RuntimeDep`, `SchedulerDep` in `web/dependencies.py`
- [ ] All routes in `web/routes/` and `web/ui/` migrated to new deps
- [ ] `web/routes/entities.py` deleted, entity route registration removed
- [ ] `alert_context()` in `web/ui/context.py` updated to accept `RuntimeQueryService`
- [ ] `HassetteHarness` and test stubs updated to wire `RuntimeQueryService`
- [ ] `web/routes/ws.py` updated: `.data_sync_service` → `.runtime_query_service`
- [ ] Owner map methods (`get_user_app_owner_map`, `get_instance_owner_map`) removed from all route handlers and templates; no `app_owner_map`/`instance_owner_map` passed as template context
- [ ] `src/hassette/web/CLAUDE.md` updated: `DataSyncDep` references replaced with `RuntimeDep`, `TelemetryDep`, `SchedulerDep`
- [ ] WebSocket broadcast stays on `RuntimeQueryService`
- [ ] `BusService.get_all_listener_metrics()` and `get_listener_metrics_by_owner()` deleted
- [ ] `SchedulerService.get_execution_history()` deleted
- [ ] `test_runtime_query_service.py` passes
- [ ] `test_telemetry_query_service.py` passes (integration, real SQLite)
- [ ] Full suite `uv run pytest -n auto` passes
- [ ] `uv run pyright` passes
