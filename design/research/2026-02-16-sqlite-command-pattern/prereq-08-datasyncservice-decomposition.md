# Prereq 8: DataSyncService Decomposition

**Status**: Decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 4: Frontend query requirements](./prereq-04-frontend-query-requirements.md) — defines the query patterns the new layer(s) must serve
- [Prereq 5: Schema design](./prereq-05-schema-design.md) — DB structure for telemetry queries
- [Prereq 7: Alembic setup / DatabaseService](./prereq-07-alembic-setup.md) — `DatabaseService` provides the `aiosqlite` connection consumed by `TelemetryQueryService`

## Dependents

- None (implementation-time concern, but shapes the web layer migration)

## Problem

`DataSyncService` (`core/data_sync_service.py`) is a monolithic facade that aggregates data from multiple in-memory sources (BusService, SchedulerService, AppHandler, StateProxy, LogCaptureHandler, event buffer) and presents it to the web layer. It was a proof of concept — every web route depends on `DataSyncDep`.

With the DB migration:
- Telemetry reads (listener metrics, job execution history, session data) move from in-memory structures to DB queries
- Entity state reads are no longer needed (entity page removed, `web/routes/entities.py` to be deleted)
- Scheduler runtime state (`next_run`, `cancelled`) is accessed via direct `SchedulerService` injection rather than through the facade
- Runtime state reads (app status, logs, events, system status) stay in-memory
- The "sync" in the name was never accurate — it's a read-only query layer, not a synchronization mechanism

The facade mixes two fundamentally different data sources with different characteristics (DB queries with I/O latency returning historical data vs in-memory lookups that are instant and return live state). Keeping them in one class obscures this and makes it harder to reason about route performance.

## Method audit

### Current public methods (20 total)

Excludes lifecycle hooks (`create()`, `on_initialize()`, `on_shutdown()`) and `config_log_level` property. Classified by destination after decomposition:

**TELEMETRY (4 existing methods → `TelemetryQueryService`, plus new methods for prereq 4 §4-9):**

| Method | Current source | DB replacement |
|--------|---------------|----------------|
| `get_listener_metrics(owner=)` | `BusService._listener_metrics` | Per-app listener summary query (prereq 4 §1) |
| `get_listener_metrics_for_instance(app_key, index)` | Same, filtered | Same query scoped to instance |
| `get_bus_metrics_summary()` | Aggregates from `_listener_metrics` | Global summary cards query (prereq 4 §3) |
| `get_job_execution_history(limit=, owner=)` | `SchedulerService._execution_log` | Per-app job summary query (prereq 4 §2) |

New query methods (not yet on `DataSyncService` — added to `TelemetryQueryService` during DB implementation): handler invocation drill-down (§4), job execution drill-down (§5), error drill-down (§6), slow handler detection (§7), session list (§8), current session summary (§9).

**REMOVED (6 methods — deleted entirely):**

| Method | Reason |
|--------|--------|
| `get_entity_state(entity_id)` | Entity page removed |
| `get_all_entity_states()` | Entity page removed |
| `get_domain_states(domain)` | Entity page removed |
| `get_scheduled_jobs(owner=)` | Routes inject `SchedulerService` directly |
| `get_scheduled_jobs_for_instance(app_key, index)` | Routes inject `SchedulerService` directly |
| `get_scheduler_summary()` | Routes inject `SchedulerService` directly |

**RUNTIME STATE (5 methods → `RuntimeQueryService`):**

| Method | Source | Notes |
|--------|--------|-------|
| `get_app_status_snapshot()` | `AppHandler` registry | Live app lifecycle state |
| `get_all_manifests_snapshot()` | `AppHandler` registry | App configuration metadata |
| `get_recent_logs(limit=, app_key=, level=)` | `LogCaptureHandler._buffer` | In-memory ring buffer |
| `get_recent_events(limit=)` | `DataSyncService._event_buffer` | In-memory ring buffer |
| `get_system_status()` | Multiple in-memory sources | Aggregates uptime, connection state, app counts |

**INFRASTRUCTURE (3 methods → `RuntimeQueryService`):**

| Method | Notes |
|--------|-------|
| `register_ws_client()` | WebSocket client management |
| `unregister_ws_client(queue)` | WebSocket client management |
| `broadcast(message)` | WebSocket push to all connected clients |

**RETIRED (2 methods — deleted entirely):**

| Method | Why retired |
|--------|------------|
| `get_user_app_owner_map()` | Only needed to translate `app_key` → `owner_id` for in-memory telemetry lookups. DB queries use `app_key`/`instance_index` directly. |
| `get_instance_owner_map()` | Same reason. Scheduler routes that need runtime state inject `SchedulerService` directly. |

### Lifecycle and factory

`create()`, `on_initialize()`, `on_shutdown()`, and `config_log_level` are internal — they follow the new service, not a classification decision.

## Consumer patterns

Current `DataSyncDep` usage across the web layer, mapped to new dependencies:

### API routes (`web/routes/`)

| File | Methods called | New dep(s) |
|------|---------------|------------|
| `apps.py` | `get_app_status_snapshot()`, `get_all_manifests_snapshot()` | `RuntimeDep` |
| `entities.py` | `get_entity_state()`, `get_all_entity_states()`, `get_domain_states()` | **Delete file** |
| `scheduler.py` | `get_scheduled_jobs()`, `get_job_execution_history()` | `TelemetryDep` + `SchedulerDep` |
| `bus.py` | `get_listener_metrics()`, `get_bus_metrics_summary()` | `TelemetryDep` |
| `events.py` | `get_recent_events()` | `RuntimeDep` |
| `health.py` | `get_system_status()` | `RuntimeDep` |
| `logs.py` | `get_recent_logs()` | `RuntimeDep` |

### UI full-page routes (`web/ui/router.py`)

| Route | Methods called | New dep(s) |
|-------|---------------|------------|
| `/` (dashboard) | `get_all_manifests_snapshot()`, `get_recent_events()`, `get_recent_logs()` | `RuntimeDep` |
| `/apps` | `get_all_manifests_snapshot()` | `RuntimeDep` |
| `/logs` | `get_recent_logs()`, `get_all_manifests_snapshot()` | `RuntimeDep` |
| `/scheduler` | `get_user_app_owner_map()`, `get_instance_owner_map()`, `get_scheduled_jobs()`, `get_job_execution_history()` | `TelemetryDep` + `SchedulerDep` |
| `/bus` | `get_user_app_owner_map()`, `get_instance_owner_map()`, `get_listener_metrics()` | `TelemetryDep` |
| `/apps/{app_key}` | `get_all_manifests_snapshot()`, `get_listener_metrics_for_instance()`, `get_scheduled_jobs_for_instance()`, `get_recent_logs()` | `RuntimeDep` + `TelemetryDep` + `SchedulerDep` |
| `/apps/{app_key}/{index}` | Same as above | `RuntimeDep` + `TelemetryDep` + `SchedulerDep` |

### UI partials (`web/ui/partials.py`)

| Partial | Methods called | New dep(s) |
|---------|---------------|------------|
| `app-list`, `app-row/{app_key}` | `get_app_status_snapshot()` | `RuntimeDep` |
| `log-entries` | `get_recent_logs()` | `RuntimeDep` |
| `manifest-list` | `get_all_manifests_snapshot()` | `RuntimeDep` |
| `dashboard-app-grid` | `get_all_manifests_snapshot()` | `RuntimeDep` |
| `dashboard-timeline` | `get_recent_events()` | `RuntimeDep` |
| `dashboard-logs` | `get_recent_logs()` | `RuntimeDep` |
| `alert-failed-apps` | `alert_context()` helper → `get_all_manifests_snapshot()` | `RuntimeDep` |
| `scheduler-jobs` | `get_user_app_owner_map()`, `get_instance_owner_map()`, `get_scheduled_jobs()` | `TelemetryDep` + `SchedulerDep` |
| `scheduler-history` | `get_user_app_owner_map()`, `get_instance_owner_map()`, `get_job_execution_history()` | `TelemetryDep` |
| `bus-listeners` | `get_user_app_owner_map()`, `get_instance_owner_map()`, `get_listener_metrics()` | `TelemetryDep` |
| `app-detail-listeners/{app_key}` | `get_instance_owner_map()`, `get_listener_metrics()` | `TelemetryDep` |
| `app-detail-jobs/{app_key}` | `get_instance_owner_map()`, `get_scheduled_jobs()` | `TelemetryDep` + `SchedulerDep` |
| `instance-listeners/{app_key}/{index}` | `get_listener_metrics_for_instance()` | `TelemetryDep` |
| `instance-jobs/{app_key}/{index}` | `get_scheduled_jobs_for_instance()` | `SchedulerDep` |

### Pattern summary

- **Most routes need only runtime state** — dashboard, apps, logs, health, events → `RuntimeDep` only
- **A few routes need only telemetry** — bus page, bus API → `TelemetryDep` only
- **Scheduler routes need telemetry + scheduler** — DB for registration/history, `SchedulerService` for `next_run`/`cancelled`
- **App detail needs runtime + telemetry** — manifests/logs from runtime, listener/job data from DB
- **Entity routes are deleted** — entity page was removed, `web/routes/entities.py` to be cleaned up

## Decisions made

### Decision 1: Decompose into two services

**Not** a single renamed facade. **Not** 7+ micro-services. Two services split by data source:

| Service | Extends | Data source | Characteristics |
|---------|---------|-------------|-----------------|
| **`TelemetryQueryService`** (new) | `Resource` | `DatabaseService` (SQLite) | Async I/O, latency, historical data, SQL queries |
| **`RuntimeQueryService`** (renamed from `DataSyncService`) | `Resource` | In-memory services | Instant reads, live state, event buffers, WS broadcast |

**Why two, not one:** The data sources have fundamentally different performance characteristics. DB queries have I/O latency and return historical data. In-memory reads are instant and return live state. Keeping them in one class obscures this and makes it harder to reason about route performance.

**Why two, not seven:** Most of the potential groupings (app, log, event, system) are 1-3 methods each with no internal state. Extracting them into separate services creates overhead (registration, lifecycle, DI aliases) for zero cohesion benefit. The meaningful boundary is data source, not data domain.

### Decision 2: Service boundaries

#### `TelemetryQueryService` (new, built during DB implementation)

Depends on `DatabaseService` (the `aiosqlite` connection manager from prereq 7). Implements the query patterns from prereq 4:

| Method | Prereq 4 query | Replaces |
|--------|----------------|----------|
| Per-app listener summary | §1 | `get_listener_metrics(owner=)` |
| Per-app listener summary (scoped) | §1 | `get_listener_metrics_for_instance(app_key, index)` |
| Global summary cards | §3 | `get_bus_metrics_summary()` |
| Per-app job summary | §2 | `get_job_execution_history(limit=, owner=)` |
| Handler invocation drill-down | §4 | **NEW** — currently missing from UI |
| Job execution drill-down | §5 | **NEW** |
| Error drill-down | §6 | **NEW** |
| Slow handler detection | §7 | **NEW** |
| Session list | §8 | **NEW** |
| Current session summary | §9 | **NEW** |
| Retention cleanup | — | **NEW** — periodic `DELETE WHERE timestamp < ?` |

All queries use `app_key` + `instance_index` directly (DB columns on parent tables, per prereq 5). No owner-mapping needed. Session-scoped variants via optional `session_id` parameter (prereq 4 session scoping).

#### `RuntimeQueryService` (renamed/slimmed `DataSyncService`)

Depends on the same in-memory services as today, minus the ones being removed:

| Method | Source | Notes |
|--------|--------|-------|
| `get_app_status_snapshot()` | `AppHandler` | Live app lifecycle |
| `get_all_manifests_snapshot()` | `AppHandler` | App configuration metadata |
| `get_recent_logs(limit=, app_key=, level=)` | `LogCaptureHandler` | In-memory ring buffer |
| `get_recent_events(limit=)` | Internal `_event_buffer` | In-memory ring buffer, event subscriptions |
| `get_system_status()` | Multiple | Aggregates uptime, connection, app counts |
| `register_ws_client()` | Internal `_ws_clients` | WebSocket management |
| `unregister_ws_client(queue)` | Internal `_ws_clients` | WebSocket management |
| `broadcast(message)` | Internal `_ws_clients` | WebSocket push |

**Drops:**
- Entity methods (entity page removed)
- Scheduler methods (routes inject `SchedulerService` directly for runtime state like `next_run`/`cancelled`)
- Listener/bus metrics methods (→ `TelemetryQueryService`)
- Owner-mapping methods (no longer needed — see Decision 4)

#### `SchedulerService` (existing, injected directly)

Scheduler routes that need runtime state (`next_run`, `cancelled`) inject `SchedulerService` directly rather than going through a facade. This is consistent with prereq 4's determination that `next_run` and `cancelled` are in-memory runtime state, not telemetry.

- DB registration metadata and execution history come from `TelemetryQueryService`
- Route handlers merge DB + runtime data as needed (e.g., scheduler page shows registration metadata from DB alongside `next_run` from `SchedulerService`)

### Decision 3: DI migration

Replace the single `DataSyncDep` with three focused deps:

```python
# web/dependencies.py

def get_telemetry(request: Request) -> "TelemetryQueryService":
    return request.app.state.hassette.telemetry_query_service

def get_runtime(request: Request) -> "RuntimeQueryService":
    return request.app.state.hassette.runtime_query_service

def get_scheduler(request: Request) -> "SchedulerService":
    return request.app.state.hassette.scheduler_service

TelemetryDep = Annotated["TelemetryQueryService", Depends(get_telemetry)]
RuntimeDep = Annotated["RuntimeQueryService", Depends(get_runtime)]
SchedulerDep = Annotated["SchedulerService", Depends(get_scheduler)]
```

**Route migration by dep pattern:**

| Pattern | Routes | Old dep | New dep(s) |
|---------|--------|---------|------------|
| Runtime only | Dashboard, apps, logs, events, health, most partials | `DataSyncDep` | `RuntimeDep` |
| Telemetry only | Bus page, bus API, bus partials, scheduler history | `DataSyncDep` | `TelemetryDep` |
| Telemetry + Scheduler | Scheduler page, scheduler-jobs partial | `DataSyncDep` | `TelemetryDep` + `SchedulerDep` |
| Runtime + Telemetry | App detail page | `DataSyncDep` | `RuntimeDep` + `TelemetryDep` |
| Runtime + Telemetry + Scheduler | App detail (with jobs) | `DataSyncDep` | `RuntimeDep` + `TelemetryDep` + `SchedulerDep` |
| Deleted | Entity routes | `DataSyncDep` | — |

**`DataSyncDep` deleted** — no compatibility shim. Clean cutover. The old `get_data_sync()` function and `DataSyncDep` alias are removed.

### Decision 4: Owner-mapping methods — retire

`get_user_app_owner_map()` and `get_instance_owner_map()` are deleted entirely.

**Why they existed:** The in-memory telemetry stores (e.g., `BusService._listener_metrics`) are keyed by `owner_id` — an opaque string like `"KitchenLights.KitchenLights.0"`. Web routes that display data per-app needed to translate `app_key` → `owner_id` to look up the right metrics. These facade methods performed that translation.

**Why they're no longer needed:**
- `TelemetryQueryService` queries by `app_key`/`instance_index` directly (DB columns on `listeners` and `scheduled_jobs` tables, per prereq 5 schema)
- `SchedulerService` is injected directly for runtime state — its existing methods already accept `owner_id`, and callers that have `app_key` can resolve via `SchedulerService` itself if needed
- No remaining consumer requires the translation

## Consistency with other prereqs

| Prereq | Check |
|--------|-------|
| **Prereq 1** (data model) | Parent tables (`listeners`, `scheduled_jobs`) use `app_key` + `instance_index` as natural keys — `TelemetryQueryService` queries these directly, no owner translation needed |
| **Prereq 4** (query requirements) | All 9 query patterns map to `TelemetryQueryService` methods. "Data that stays in-memory" table: `next_run`/`cancelled` → `SchedulerService` directly, app status/events/logs → `RuntimeQueryService`, entity states → removed |
| **Prereq 5** (schema) | All tables queried only by `TelemetryQueryService`. Execution tables JOIN to parent tables for `app_key` filtering — no `app_key` on execution rows themselves |
| **Prereq 7** (DatabaseService) | `aiosqlite` connection consumed only by `TelemetryQueryService`. `RuntimeQueryService` never touches the DB |

## Implementation notes

These are not decisions — they're practical observations for the implementer:

- **Rename first, decompose second**: The simplest migration path is to rename `DataSyncService` → `RuntimeQueryService` (removing dropped methods), then extract `TelemetryQueryService` as a new service when DB queries are ready. This avoids a big-bang change.
- **Entity cleanup**: Delete `web/routes/entities.py` and remove entity routes from the router registration. The entity page link in the sidebar (if any) should also be removed.
- **`HassetteHarness` impact**: The test harness wires `DataSyncService` — it will need updating to wire `RuntimeQueryService` instead. `TelemetryQueryService` tests will use `DatabaseService` fixtures from prereq 7.
- **WebSocket broadcast stays on `RuntimeQueryService`**: The WS infrastructure is tied to live state changes (event buffer, app status updates). It doesn't interact with the DB.
- **`alert_context()` helper**: `web/ui/context.py` defines an `alert_context()` helper function that accepts a `DataSyncService` argument and calls `get_all_manifests_snapshot()`. Update to accept `RuntimeQueryService` instead.
