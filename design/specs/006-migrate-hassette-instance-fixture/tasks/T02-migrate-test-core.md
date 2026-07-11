---
task_id: "T02"
title: "Migrate test_core.py to public properties"
status: "planned"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "FR#8", "AC#1", "AC#4"]
---

## Summary
Migrate all private-attribute service access in `tests/integration/test_core.py` to use public properties. Rewrite `test_constructor_registers_background_services` to assert type-membership via `hassette_instance.children`. Annotate remaining state-machine test sites (SessionManager internals, `_loop`, `_loop_watchdog`, `_fatal_shutdown_reason` writes) with `# coordinator-internal`.

## Target Files
- modify: `tests/integration/test_core.py`

## Prompt
In `tests/integration/test_core.py`, perform these changes:

### 1. Rewrite `test_constructor_registers_background_services` (lines 44-86)

Replace the per-service isinstance assertions and expected_children list with a `children`-based pattern. The test should:
- Get `child_types = {type(c) for c in hassette_instance.children}`
- Build the expected set of all types registered by `wire_services()`
- Assert strict equality: `assert child_types == expected_types` (not a subset check — this ensures no types are missing AND no unexpected types are added)
- Keep the `hassette_instance.api is not None` assertion (uses public property)

The expected types set must include ALL 22 types registered by `wire_services()` (`core.py:183-216`): `SyncExecutorService`, `EventStreamService`, `DatabaseService`, `LoggingService`, `CommandExecutor`, `BusService`, `SchedulerService`, `SessionManager`, `ServiceWatcher`, `WebsocketService`, `FileWatcherService`, `WebUiWatcherService`, `AppHandler`, `ApiResource`, `StateProxy`, `RuntimeQueryService`, `TelemetryQueryService`, `WebApiService`, `Bus`, `Scheduler`, `StateManager`, `Api`. Import any types not already imported (`SyncExecutorService`, `StateProxy`, `SessionManager`, `WebUiWatcherService` may need adding).

### 2. Replace private-attr reads with public properties

For every `hassette_instance._<service>` access outside the rewritten constructor test, replace with the public property:
- `._database_service` → `.database_service`
- `._session_manager` → `.session_manager` (new property from T01)
- `._event_stream_service` → `.event_stream_service` (new property from T01)
- `._bus` → `.bus` (new property from T01)
- `._bus_service` → `.bus_service`
- `._app_handler` → `.app_handler`
- `._loop_thread_id` → `.loop_thread_id`

### 3. Annotate state-machine test sites

Add `# coordinator-internal` annotation to remaining private-attr accesses that test internal state:
- `hassette_instance._loop = running_loop` (line ~105) — direct loop assignment for emulating run_forever
- `hassette_instance._loop` reads in assertions (line ~203)
- `hassette_instance._loop_watchdog` assertion (line ~268)
- `sm._session_id`, `sm._session_error`, `sm._database_service`, `sm._session_lock` accesses in `test_concurrent_crash_and_finalize_are_serialized` (lines ~324-350)

Place the annotation as a trailing comment on the line, or on the preceding line if the line is too long.

### 4. Handle `_fatal_shutdown_reason` reads vs writes

- Reads: Replace with public `hassette_instance.fatal_shutdown_reason` (property already exists at `core.py:659-662`)
- Writes: Keep private access with `# coordinator-internal` annotation

## Focus
- `test_core.py` has 22 tests. The constructor test is the most complex rewrite.
- `fatal_shutdown_reason` has a public read-only property already (`core.py:659`). Only writes need private access.
- Some tests assign `hassette_instance._app_handler = SimpleNamespace(...)` with `# pyright: ignore[reportAttributeAccessIssue]`. The public `app_handler` property is read-only (no setter). These assignment sites should keep private access with `# coordinator-internal` annotation since they're setting up test conditions.
- Same applies to `hassette_instance.wait_for_ready = AsyncMock(...)` and `hassette_instance.shutdown = AsyncMock(...)` — these mock public methods, which is standard test practice and doesn't need annotation.
- Remove any `pyright: ignore[reportAttributeAccessIssue]` comments that were only needed because of private attr access, but keep them where they suppress legitimate type issues (e.g., assigning a Mock to a typed attribute).

## Verify
- [ ] FR#4: `test_constructor_registers_background_services` asserts type-membership via `children`, no per-service isinstance checks using private attrs
- [ ] FR#5: All service reads in test_core.py use public properties (grep for `hassette_instance._` shows only annotated coordinator-internal sites)
- [ ] FR#8: All remaining private-attr accesses have `# coordinator-internal` annotation
- [ ] AC#1: Zero `hassette_instance._<service>` access for services with public properties
- [ ] AC#4: All remaining private-attr sites have `# coordinator-internal`
