---
task_id: "T03"
title: "Migrate source access sites and promote database constants"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#7", "AC#2", "AC#6"]
---

## Summary

Mechanically update all source files that access HassetteConfig fields to use the new nested paths, and promote the 7 hardcoded database service constants to read from DatabaseConfig. This is the largest task by file count (~55 source files) but each individual change is a straightforward rename. No behavioral changes — only access path updates and constant removal.

## Prompt

### Step 1: Remove database service module constants

In `src/hassette/core/database_service.py`, remove the 7 module-level constants (lines 28-47):
- `_HEARTBEAT_INTERVAL_SECONDS`
- `_RETENTION_INTERVAL_SECONDS`
- `_SIZE_FAILSAFE_INTERVAL_SECONDS`
- `_SIZE_FAILSAFE_MAX_ITERATIONS`
- `_SIZE_FAILSAFE_DELETE_BATCH`
- `_SIZE_FAILSAFE_VACUUM_PAGES`
- `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES`

Replace every reference to these constants with `self.hassette.config.database.<field_name>`. Search the entire file for each constant name to find all usage sites.

### Step 2: Migrate `config_log_level` properties on all service classes

25 service/resource classes override `config_log_level` to return a specific log level field. Update each to reference the nested path. Pattern:

**Before:** `return self.hassette.config.database_service_log_level`
**After:** `return self.hassette.config.logging.database_service`

Files with `config_log_level` overrides (from grep):
- `src/hassette/core/database_service.py` → `.logging.database_service`
- `src/hassette/core/bus_service.py` → `.logging.bus_service`
- `src/hassette/core/scheduler_service.py` (2 classes) → `.logging.scheduler_service`
- `src/hassette/core/app_handler.py` → `.logging.app_handler`
- `src/hassette/core/web_api_service.py` → `.logging.web_api`
- `src/hassette/core/websocket_service.py` → `.logging.websocket`
- `src/hassette/core/service_watcher.py` → `.logging.service_watcher`
- `src/hassette/core/file_watcher.py` → `.logging.file_watcher`
- `src/hassette/core/event_stream_service.py` → `.logging.bus_service` (peer of bus service)
- `src/hassette/core/runtime_query_service.py` → `.logging.web_api` (child of web API)
- `src/hassette/core/telemetry_query_service.py` → `.logging.web_api` (child of web API)
- `src/hassette/core/session_manager.py` → `.logging.database_service` (child of DB service)
- `src/hassette/core/web_ui_watcher.py` → `.logging.file_watcher` (child of file watcher)
- `src/hassette/core/api_resource.py` → `.logging.api`
- `src/hassette/core/state_proxy.py` → `.logging.state_proxy`
- `src/hassette/core/app_lifecycle_service.py` → `.logging.app_handler` (child of app handler)
- `src/hassette/core/command_executor.py` → `.logging.command_executor`
- `src/hassette/task_bucket/task_bucket.py` → `.logging.task_bucket`
- `src/hassette/scheduler/scheduler.py` → `.logging.scheduler_service`
- `src/hassette/state_manager/state_manager.py` → `.logging.state_proxy` (child of state proxy)
- `src/hassette/app/app.py` → `.logging.apps`
- `src/hassette/api/api.py` → `.logging.api`
- `src/hassette/api/sync.py` → `.logging.api`
- `src/hassette/bus/bus.py` → `.logging.bus_service`

### Step 3: Migrate remaining config access sites by group

For each group, search for the old access pattern and replace with the nested path. Use the design.md field mapping tables for exact renames.

**Database fields:** `config.db_path` → `config.database.path`, `config.db_retention_days` → `config.database.retention_days`, `config.db_max_size_mb` → `config.database.max_size_mb`, `config.db_migration_timeout_seconds` → `config.database.migration_timeout_seconds`, `config.db_write_queue_max` → `config.database.write_queue_max`, `config.telemetry_write_queue_max` → `config.database.telemetry_write_queue_max`.
Key files: `database_service.py`, `command_executor.py`, `database_service.py`.

**WebSocket fields:** `config.websocket_*` → `config.websocket.*` (strip prefix).
Key file: `websocket_service.py` (19 accesses).

**Lifecycle fields:** `config.startup_timeout_seconds` → `config.lifecycle.startup_timeout_seconds`, `config.app_startup_timeout_seconds` → `config.lifecycle.app_startup_timeout_seconds`, etc.
Key files: `core.py`, `app_handler.py`, `resources/base.py`.

**Web API fields:** `config.run_web_api` → `config.web_api.run`, `config.web_api_host` → `config.web_api.host`, etc.
Key files: `web_api_service.py`, `web/app.py`.

**App fields:** `config.autodetect_apps` → `config.app.autodetect`, `config.app_dir` → `config.app.directory`, `config.app_manifests` → `config.app.manifests`, etc.
Key files: `app_handler.py`, `app_registry.py`, `core.py`.

**Scheduler fields:** `config.scheduler_*` → `config.scheduler.*` (strip prefix).
Key files: `scheduler_service.py`, `scheduler/scheduler.py`, `scheduler/classes.py`.

**File watcher fields:** `config.file_watcher_*` → `config.file_watcher.*`, `config.watch_files` → `config.file_watcher.watch_files`.
Key files: `file_watcher.py`, `core.py`.

**Logging fields:** `config.log_level` → `config.logging.log_level`, `config.log_format` → `config.logging.log_format`, `config.log_retention_days` → `config.logging.log_retention_days`, `config.log_all_events` → `config.logging.all_events`, etc.
Key files: `core.py`, `web/routes/logs.py`, `database_service.py`.

**Bus fields:** `config.bus_excluded_domains` and `config.bus_excluded_entities` stay root (no migration needed).

### Step 4: Verify no stale references remain

After all renames, grep for the old flat field patterns to confirm no references were missed:
```
grep -rn 'config\.db_\|config\.websocket_\|config\.scheduler_\|config\.file_watcher_\|config\.web_api_\|config\.run_web_api\|config\.run_web_ui\|config\.autodetect_apps\|config\.app_dir\|_log_level\b' src/hassette/ --include='*.py'
```

Filter out false positives (e.g., the field definitions in models.py, comments, string literals).

## Focus

- `src/hassette/core/database_service.py` — highest complexity: remove 7 constants + rename 12 field accesses. Constants are used in `execute()` method's scheduling loops.
- `src/hassette/core/websocket_service.py` — 19 config accesses, all `websocket_*` prefix stripping.
- `src/hassette/core/core.py` — 22 config accesses spanning multiple groups (lifecycle, app, logging, web_api). Careful with the breadth.
- `src/hassette/core/bus_service.py` — 32 accesses but most are `config_log_level` (handled in Step 2). The `bus_excluded_*` fields stay root.
- `src/hassette/resources/base.py:248` — `config.data_dir` stays as `config.data_dir` (root field, no rename needed).
- The `config_log_level` property on child resources often returns the PARENT service's log level (e.g., `telemetry_query_service` returns `database_service_log_level`). Verify the nested path maps to the correct parent.
- `src/hassette/web/routes/logs.py:102` — `config.log_retention_days` → `config.logging.log_retention_days`.

## Verify
- [ ] FR#7: All 7 database service constants (`_HEARTBEAT_INTERVAL_SECONDS` through `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES`) are removed from `database_service.py` and replaced with reads from `config.database.*`
- [ ] AC#2: Grep for old flat patterns (`config.db_`, `config.websocket_`, `config.scheduler_`, `config.file_watcher_`, `config.web_api_`, `config.run_web_api`, `_log_level`) in `src/hassette/` returns no matches outside of `models.py` definitions and `AliasChoices` declarations
- [ ] AC#6: `database_service.py` reads heartbeat_interval_seconds, retention_interval_seconds, size_failsafe_interval_seconds, size_failsafe_max_iterations, size_failsafe_delete_batch, size_failsafe_vacuum_pages, and max_consecutive_heartbeat_failures from `self.hassette.config.database.*` instead of module constants
