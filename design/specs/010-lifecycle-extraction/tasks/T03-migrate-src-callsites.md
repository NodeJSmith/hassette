---
task_id: "T03"
title: "Migrate all src/ call sites to module functions"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#4"]
---

## Summary

Update all 35 src/ files to import and call the new module-level functions from `resources/lifecycle.py` and `resources/operations.py` instead of calling methods via `self.method()` or `instance.method()`. The old method bodies remain on the classes temporarily (deleted in T06) so tests continue to pass during this transition.

## Target Files

- modify: `src/hassette/resources/base.py`
- modify: `src/hassette/resources/service.py`
- modify: `src/hassette/core/database_service.py`
- modify: `src/hassette/core/websocket_service.py`
- modify: `src/hassette/core/bus_service.py`
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/core/logging_service.py`
- modify: `src/hassette/core/sync_executor_service.py`
- modify: `src/hassette/core/web_api_service.py`
- modify: `src/hassette/core/web_ui_watcher.py`
- modify: `src/hassette/core/event_stream_service.py`
- modify: `src/hassette/core/runtime_query_service.py`
- modify: `src/hassette/core/session_manager.py`
- modify: `src/hassette/core/file_watcher.py`
- modify: `src/hassette/core/command_executor.py`
- modify: `src/hassette/core/telemetry/query_service.py`
- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/core/core.py`
- modify: `src/hassette/core/service_watcher.py`
- modify: `src/hassette/core/app_handler.py`
- modify: `src/hassette/core/api_resource.py`
- modify: `src/hassette/core/state_proxy.py`
- modify: `src/hassette/api/api.py`
- modify: `src/hassette/api/sync.py`
- modify: `src/hassette/bus/bus.py`
- modify: `src/hassette/bus/sync.py`
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `src/hassette/scheduler/sync.py`
- modify: `src/hassette/state_manager/state_manager.py`
- modify: `src/hassette/app/app.py`
- modify: `src/hassette/task_bucket/task_bucket.py`
- modify: `src/hassette/test_utils/app_harness.py`
- modify: `src/hassette/test_utils/harness.py`
- modify: `src/hassette/test_utils/recording_api.py`
- modify: `src/hassette/test_utils/reset.py`
- read: `src/hassette/resources/lifecycle.py`
- read: `src/hassette/resources/operations.py`

## Prompt

For each of the 35 files listed in Target Files (all `modify` entries), apply these mechanical transformations:

**Pattern 1 — Internal `self.` calls (Service subclasses, Resource methods):**
```python
# Before
await self.handle_failed(exc)
self.mark_ready(reason="initialized")

# After
from hassette.resources.lifecycle import handle_failed, mark_ready
await handle_failed(self, exc)
mark_ready(self, reason="initialized")
```

**Pattern 2 — External instance calls (AppLifecycleService, ServiceWatcher, test utils):**
```python
# Before
inst.mark_ready(reason="initialized")
await svc.restart()

# After
from hassette.resources.lifecycle import mark_ready
from hassette.resources.operations import restart
mark_ready(inst, reason="initialized")
await restart(svc)
```

**Pattern 3 — `register_task_bucket_factory` (task_bucket.py):**
```python
# Before
Resource.register_task_bucket_factory(factory)

# After
from hassette.resources.operations import register_task_bucket_factory
register_task_bucket_factory(factory)
```

**Pattern 4 — `_run_hooks` and `_ordered_children_for_shutdown` (base.py):**
```python
# Before (in Resource.initialize, Resource.shutdown, Resource.cleanup)
await self._run_hooks(hooks, continue_on_error=True)

# After
from hassette.resources.operations import run_hooks
await run_hooks(self, hooks, continue_on_error=True)
```

Add the appropriate imports at the top of each file. Group lifecycle and operations imports separately.

Do NOT delete the old methods from LifecycleMixin or Resource — they stay until T06 so tests pass.

After all migrations, run `prek -a` to verify lint and type checking pass.

## Focus

- The highest-volume call site is `self.mark_ready(reason=...)` — ~37 occurrences across service `on_initialize()` hooks. Each becomes `mark_ready(self, reason=...)`.
- `base.py` has internal cross-calls: `initialize()` calls `handle_starting()`, `start_children_and_wait()`, `handle_running()`, `_run_hooks()`. All become function calls with `self` as first arg.
- `service.py` has `_serve_wrapper()` which calls `handle_running()`, `handle_stop()`, `handle_crash()`, `handle_failed()`. All become function calls.
- `app_lifecycle_service.py:138` has `inst.mark_ready(reason="initialized")` — external call pattern.
- `task_bucket.py:434` calls `Resource.register_task_bucket_factory(factory)` — classmethod pattern.
- `core.py` has `_on_children_stopped()` and `shutdown()` with lifecycle calls.
- Test utils (`app_harness.py`, `harness.py`, `recording_api.py`, `reset.py`) call lifecycle methods on instances.

## Verify

- [ ] FR#4: All framework call sites in `src/` that T03 targets call module-level functions. Verify with two checks: (1) `prek -a` passes (type checker confirms all migrated imports resolve). (2) Spot-check key call-site files: `grep -n 'self\.handle_failed\|self\.mark_ready\|self\.handle_crash\|self\.handle_stop\|self\.handle_running\|self\.handle_starting\|self\.restart\|self\.start_children_and_wait\|self\._run_hooks' src/hassette/resources/service.py src/hassette/core/app_lifecycle_service.py src/hassette/core/core.py src/hassette/core/service_watcher.py src/hassette/task_bucket/task_bucket.py` returns no results. Note: the old method bodies in `mixins.py` and `base.py` still contain internal `self.method()` calls — these are dead code deleted in T06, not T03 call-site failures.
