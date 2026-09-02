# Tests: unit/core

Fixtures below are defined in family-scoped `_fixtures_*.py` modules in this directory
(`_fixtures_app_lifecycle.py`, `_fixtures_command_executor.py`, `_fixtures_bus_scheduler.py`,
`_fixtures_blocking_io.py`, `_fixtures_service_watcher.py`, `_fixtures_telemetry.py`) and
re-exported from `conftest.py`. Import from `.conftest` as before — the re-export keeps that
surface stable; only the definitions moved.

## Available fixtures (re-exported from this directory's conftest.py)

- `mock_hassette` — `make_mock_hassette()` wired for `AppLifecycleService` tests
- `mock_registry`, `mock_factory`, `mock_manifest`, `mock_app_instance` — mocked collaborators for lifecycle tests
- `lifecycle_service` — `AppLifecycleService` built from the mocks above
- `telemetry_db`, `telemetry_repo`, `telemetry_session_id` — SQLite-backed telemetry test chain

## Shared helpers (module-level functions, not fixtures)

- `set_registry_apps(registry, apps)` — configures a `mock_registry`'s `__contains__`, `app_keys()`, `get_running_apps()`, and `get()` from an `apps`-shaped dict (`dict[str, dict[int, App]]`); use instead of assigning `mock_registry.apps = ...` directly (that attribute no longer exists on the real `AppRegistry`)
- `make_executor(**kw)` — real `CommandExecutor` with dependencies mocked out
- `init_executor(queue_max=10)` — real `CommandExecutor` set up for write-pipeline tests (bounded queue, capacity-warning config, real `ready_event`); shared by `test_command_executor_pipeline_queue.py`, `test_command_executor_pipeline_persist.py`, `test_command_executor_pipeline_serve.py`
- `make_invocation(**kw)` — `ExecutionRecord` for a handler execution, defaults tuned for the write-pipeline tests above
- `make_mock_cmd_listener(**kw)` — `MagicMock` Listener for `CommandExecutor` tests (side_effect, error_handler)
- `make_execute_job_cmd(**kw)` — `MagicMock` spec'd to `ExecuteJob` for executor tests
- `make_bus_service(**kw)`, `make_scheduler_service(**kw)` — service instances bypassing `Resource.__init__`
- `make_watcher(hassette)`, `make_watcher_hassette(**kw)` — `ServiceWatcher` test setup
- `make_blocking_io_hassette(**kw)` — minimal mock Hassette for watchdog and monkeypatch guard tests
- `make_marker_executor(**kw)` — mock executor with `ExecutionMarker` on `current_execution`
- `assert_listener_count(db, listener_id, expected, message)` — assert the number of `listeners` rows with that id
- `fetch_listener_field(db, listener_id, field)` — read one column from a `listeners` row
- `insert_committed_execution(db, session_id, **kw)` — insert and commit an `executions` row (1ms, now)
- `insert_new_session(db)` — insert a second `running` session row and return its id, for the once=True/previous-session reconciliation tests

## Key conventions

- Service factories (`make_bus_service`, `make_scheduler_service`, `make_watcher`) bypass `__init__` via `__new__` — set every attribute the real `__init__` would set.
