# Tests: unit/core

## Available fixtures (this directory's conftest.py)

- `mock_hassette` — `make_mock_hassette()` wired for `AppLifecycleService` tests
- `mock_registry`, `mock_factory`, `mock_manifest`, `mock_app_instance` — mocked collaborators for lifecycle tests
- `lifecycle_service` — `AppLifecycleService` built from the mocks above
- `telemetry_db`, `telemetry_repo`, `telemetry_session_id` — SQLite-backed telemetry test chain

## Shared helpers (module-level functions, not fixtures)

- `make_executor(**kw)` — real `CommandExecutor` with dependencies mocked out
- `make_mock_cmd_listener(**kw)` — `MagicMock` Listener for `CommandExecutor` tests (side_effect, error_handler)
- `make_execute_job_cmd(**kw)` — `MagicMock` spec'd to `ExecuteJob` for executor tests
- `make_bus_service(**kw)`, `make_scheduler_service(**kw)` — service instances bypassing `Resource.__init__`
- `make_watcher(hassette)`, `build_watcher_hassette(**kw)` — `ServiceWatcher` test setup
- `make_blocking_io_hassette(**kw)` — minimal mock Hassette for watchdog and monkeypatch guard tests
- `make_marker_executor(**kw)` — mock executor with `ExecutionMarker` on `current_execution`

## Key conventions

- Service factories (`make_bus_service`, `make_scheduler_service`, `make_watcher`) bypass `__init__` via `__new__` — set every attribute the real `__init__` would set.
