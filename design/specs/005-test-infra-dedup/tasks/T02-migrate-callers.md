---
task_id: "T02"
title: "Migrate all local factory callers to shared imports"
status: "planned"
depends_on: ["T01"]
implements: ["FR#7", "FR#12", "FR#13", "FR#15", "AC#1", "AC#2", "AC#3"]
---

## Summary
Delete all local factory definitions that are subsumed by T01's shared factories and replace them with imports. Also handles the `noop` migration (FR#12), `make_test_config` rename (FR#13), and `make_manifest` autostart addition (FR#15). This is the largest task by file count (~36 files) but every change is mechanical: delete local `def`, add `from hassette.test_utils.factories import ...`.

## Target Files
- modify: `src/hassette/test_utils/helpers.py`
- modify: `src/hassette/test_utils/web_helpers.py`
- modify: `tests/unit/conftest.py`
- modify: `tests/unit/bus/conftest.py`
- modify: `tests/unit/scheduler/conftest.py`
- modify: `tests/unit/test_scheduler_resource.py`
- modify: `tests/unit/test_scheduled_job.py`
- modify: `tests/unit/test_scheduler_job_names.py`
- modify: `tests/unit/test_task_bucket.py`
- modify: `tests/unit/test_source_tier_propagation.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `tests/unit/test_sync_executor_service_wiring.py`
- modify: `tests/unit/bus/test_invocation.py`
- modify: `tests/unit/bus/test_duration_hold.py`
- modify: `tests/unit/bus/test_bus_timeout_threading.py`
- modify: `tests/unit/bus/test_service_data_predicates.py`
- modify: `tests/unit/bus/test_duration_timer.py`
- modify: `tests/unit/core/test_bus_service_timeout.py`
- modify: `tests/unit/core/test_bus_service_error_handler.py`
- modify: `tests/unit/core/test_bus_dispatch_semaphore.py`
- modify: `tests/unit/core/test_event_filter.py`
- modify: `tests/unit/core/test_command_executor_execution_id.py`
- modify: `tests/unit/core/test_scheduler_service_reschedule.py`
- modify: `tests/unit/core/test_scheduler_service_timeout.py`
- modify: `tests/unit/core/test_scheduler_service_dequeue.py`
- modify: `tests/unit/core/test_scheduler_service_error_handler.py`
- modify: `tests/unit/core/test_loop_watchdog.py`
- modify: `tests/unit/core/test_protect_loop_monkeypatch.py`
- modify: `tests/unit/scheduler/test_scheduled_job_mark_registered.py`
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py`
- modify: `tests/unit/scheduler/test_scheduled_job_timeout.py`
- modify: `tests/unit/scheduler/test_scheduler_error_handler.py`
- modify: `tests/unit/scheduler/test_scheduler_timeout_threading.py`
- modify: `tests/unit/scheduler/test_scheduler_coroutine_conversion.py`
- modify: `tests/unit/scheduler/test_scheduler_where.py`
- modify: `tests/unit/test_recording_api.py`
- modify: `tests/unit/test_recording_api_helpers.py`
- modify: `tests/unit/test_recording_sync_facade.py`
- modify: `tests/unit/web/test_mappers.py`
- modify: `tests/integration/test_scheduler_mode.py`
- modify: `tests/integration/database/test_database_service.py`
- modify: `tests/integration/bus/test_execution_modes.py`
- modify: `tests/integration/test_app_factory_lifecycle.py`
- modify: `tests/unit/test_config_classes.py`
- modify: `tests/unit/core/test_app_registry.py`
- modify: `tests/unit/core/test_app_change_detector.py`
- modify: `tests/integration/test_sync_facades.py`
- modify: `tests/integration/web_api/test_trigger_job.py`

## Prompt
This is a large mechanical migration. For each factory consolidation, follow this pattern:

1. **Delete** the local `def make_*()` definition (or inline `Mock()` construction)
2. **Add** `from hassette.test_utils.factories import make_*` at the top of the file
3. **Update** call sites if the shared factory has different parameter names

### Migration groups (in order):

**FR#7 — Factory migrations (FR#1-6 callers):**

- **`make_scheduled_job`** replaces 9 local `make_job()` definitions that build real `ScheduledJob`s. Files: `test_scheduler_resource.py`, `test_scheduled_job.py`, `test_scheduler_job_names.py`, `scheduler/test_scheduled_job_mark_registered.py`, `scheduler/test_scheduled_job_lifecycle.py`, `scheduler/test_scheduled_job_timeout.py`, `core/test_scheduler_service_reschedule.py`, `core/test_scheduler_service_timeout.py`, `core/test_scheduler_service_dequeue.py`. Note: `make_job` in `core/test_scheduler_service_error_handler.py` returns `MagicMock` — leave it local with `# factory-local: returns MagicMock, not ScheduledJob`. The nested `make_job(label, signal)` in `tests/integration/test_scheduler.py:172` is unrelated — leave it alone.

- **`make_mock_executor`** replaces 4 identical definitions. Files: `test_bus_service_timeout.py`, `test_bus_service_error_handler.py`, `test_invocation.py`, `test_duration_hold.py`. Note: `make_executor` in `test_loop_watchdog.py` and `test_protect_loop_monkeypatch.py` build `ExecutionMarker`-based mocks — leave local with `# factory-local: ExecutionMarker-based mock, not execute=AsyncMock() pattern`.

- **`make_mock_event`** replaces 4 functionally-identical definitions. Files: `test_bus_service_timeout.py`, `test_bus_service_error_handler.py`, `test_invocation.py`, `test_bus_dispatch_semaphore.py`. Note: `make_event` in `test_duration_timer.py` (no spec) and `test_service_data_predicates.py` (SimpleNamespace) are different — leave local with `# factory-local:` annotations.

- **`make_recording_api`** replaces 3 near-identical factories. Files: `test_recording_api.py`, `test_recording_api_helpers.py`, `test_recording_sync_facade.py`.

- **`make_hassette_event`** replaces 2 definitions. Files: `test_event_filter.py`, `test_command_executor_execution_id.py`.

- **`make_mock_parent`** replaces 2 `def` variants plus 6 inline constructions. Delete defs in `tests/unit/conftest.py:85` and `tests/unit/test_scheduler_resource.py:17`. Replace inline `mock_parent = MagicMock()` + attribute assignment blocks with `make_mock_parent()` calls in: `bus/conftest.py:33-39`, `scheduler/conftest.py:42-45`, `bus/test_bus_timeout_threading.py:18-23`, `test_execution_modes.py:521`, `test_source_tier_propagation.py:74,:137`. Update `test_forgotten_await_completeness.py:33` import to `from hassette.test_utils.factories import make_mock_parent`. Update `make_api()` at `tests/unit/conftest.py:118` to import `make_mock_parent` from the shared factory.

- **`make_invoke_handler_cmd`** — delete the local duplicate in `test_command_executor_execution_id.py:53` and add import from `hassette.test_utils.factories`.

**FR#12 — noop migration:**

Replace the sync `def noop() -> None: pass` at `src/hassette/test_utils/helpers.py:45` with `async def noop() -> None: pass`. Delete `async def noop` from `tests/unit/scheduler/conftest.py:17`. Update 7 import sites in `tests/unit/scheduler/` to `from hassette.test_utils.helpers import noop`. Migrate 2 module-level reimplementations: `test_scheduler_resource.py:76`, `test_scheduled_job.py:31` (delete def, add import). Migrate 1 nested reimplementation in `test_task_bucket.py:179`, 1 in `integration/database/test_database_service.py:429`, and 17 in `integration/test_scheduler_mode.py` (replace nested `async def noop` with import at top of file, use in each test).

**FR#13 — make_test_config rename:**

Rename `make_test_config` to `make_sync_executor_config` at `tests/unit/conftest.py:47`. Update the import in `tests/unit/test_sync_executor_service_wiring.py:33` and all 3 call sites (lines 188, 216, 228). Update the internal call in `make_sync_executor_hassette()` at `tests/unit/conftest.py:58`.

**Linter exemption annotations:**

Add `# factory-local: <reason>` annotations to pre-existing local definitions that legitimately shadow shared factory names but are NOT subsumed:

- `tests/integration/test_app_factory_lifecycle.py:53` — `def make_manifest(...)` returns `AppManifest` (config-layer model), not `AppManifestInfo`. Add `# factory-local: returns AppManifest, not AppManifestInfo`
- `tests/unit/test_config_classes.py:14` — `def make_manifest(**overrides)` returns `AppManifest`. Add `# factory-local: returns AppManifest, not AppManifestInfo`
- `tests/unit/core/test_app_registry.py:510` — `def make_manifest(self, ...)` class method returning `SimpleNamespace`. Add `# factory-local: returns SimpleNamespace for registry tests`
- `tests/unit/core/test_app_change_detector.py:102` — `def make_manifest(self)` fixture factory returning `Callable`. Add `# factory-local: fixture factory returning Callable`
- `tests/integration/test_sync_facades.py:73` — `def noop(event)` sync handler taking `RawStateChangeEvent`. Add `# factory-local: sync handler with event param for facade tests`
- `tests/integration/test_sync_facades.py:84` — `def noop()` sync no-arg handler. Add `# factory-local: sync no-arg handler for facade tests`
- `tests/integration/web_api/test_trigger_job.py:20` — `def make_scheduled_job(...)` wraps `make_real_job()` with `guard_running` option. Add `# factory-local: wraps make_real_job with guard_running for trigger tests`

**FR#15 — make_manifest autostart:**

Add `autostart: bool = True` parameter to `make_manifest()` in `src/hassette/test_utils/web_helpers.py`. Pass it through to `AppManifestInfo(autostart=autostart, ...)`. Delete the local `make_manifest` duplicate in `tests/unit/web/test_mappers.py:144` and replace with import from `hassette.test_utils.web_helpers`. **Critical:** the local `make_manifest` has signature `(app_key, status, instances=None, autostart=True)` while the shared version has a different positional order (`app_key, class_name, display_name, filename, enabled, auto_loaded, status, ...`). All 8 call sites in `test_mappers.py` pass `status` as the second positional arg (e.g., `make_manifest("app_a", "stopped")`). Convert every call to use keyword arguments: `make_manifest("app_a", status="stopped")` — otherwise `status` silently maps to `class_name` and tests pass with wrong data.

## Focus
- This is a large task (~36 files). Work through each migration group methodically. Run `uv run pytest <file> -x` after each group to catch breakage early.
- For `noop` in `test_scheduler_mode.py`, the 17 nested copies are each inside a test method. Replace them all with a single `from hassette.test_utils.helpers import noop` import at the top of the file.
- `make_mock_parent` inline replacements: match the keyword args each call site was setting. Some set only `app_key`/`index`/`source_tier`/`class_name` — the shared factory's defaults for `unique_name` and `app_config` are harmless extras.
- `test_source_tier_propagation.py` has a unique field pattern (includes `unique_name`, omits `class_name`) — pass `class_name` explicitly or accept the default.
- `test_execution_modes.py:521` dynamically copies field values from `original_parent` (the live harness parent) rather than using hardcoded literals like other inline sites. When replacing with `make_mock_parent()`, pass `source_tier="framework"` explicitly — the other fields' defaults are acceptable since no test assertion reads them.
- For exempted local factories, add `# factory-local: <reason>` on the `def` line.

## Verify
- [ ] FR#7: `grep -rn "def make_recording_api\b" tests/` returns zero results (3 local definitions replaced)
- [ ] FR#7: `grep -rn "def make_hassette_event\b" tests/` returns zero results (2 local definitions replaced)
- [ ] FR#7: `grep -rn "def make_mock_parent\b" tests/` returns zero results (2 local definitions replaced; inline constructions replaced with factory calls)
- [ ] FR#7: `grep -rn "def make_invoke_handler_cmd\b" tests/` returns zero results (1 local definition replaced)
- [ ] FR#12: `noop` moved to `helpers.py` (async version), all 21 reimplementations + 7 import sites migrated
- [ ] FR#13: `make_test_config` renamed to `make_sync_executor_config` in conftest and all callers
- [ ] FR#15: `make_manifest()` in `web_helpers.py` accepts `autostart` param, local duplicate in `test_mappers.py` deleted
- [ ] AC#1: `grep -rn "def make_job\b" tests/` returns exactly 2 results
- [ ] AC#2: `grep -rn "def make_event\b" tests/` returns zero for the 4 functionally-identical definitions; legitimately-different variants remain with `# factory-local:` annotations
- [ ] AC#3: `grep -rn "def make_executor\b" tests/` returns exactly 4 results (2 real CommandExecutor + 2 ExecutionMarker-based exempt)
