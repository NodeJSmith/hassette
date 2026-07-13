---
task_id: "T05"
title: "Migrate mechanical test call sites"
status: "done"
depends_on: ["T04"]
implements: ["AC#5"]
---

## Summary

Update ~41 test files that call extracted lifecycle methods directly on resource instances (`resource.handle_failed(exc)`, `resource.mark_ready(reason=...)`, etc.) to call the module-level functions (`handle_failed(resource, exc)`, `mark_ready(resource, reason=...)`). This is entirely mechanical — same transformation pattern as T03 but applied to test code. T04 must complete first because some files appear in both the spy and mechanical lists, and T04's structural changes take priority.

## Target Files

- modify: `tests/integration/bus/conftest.py`
- modify: `tests/integration/test_core.py`
- modify: `tests/integration/test_dispatch_unification.py`
- modify: `tests/integration/test_lifecycle_propagation.py`
- modify: `tests/integration/test_resource_deps.py`
- modify: `tests/integration/test_service_watcher.py`
- modify: `tests/integration/test_state_proxy.py`
- modify: `tests/integration/test_web_ui_watcher.py`
- modify: `tests/integration/test_websocket_service.py`
- modify: `tests/system/test_shutdown.py`
- modify: `tests/unit/core/conftest.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/core/test_command_executor_pipeline.py`
- modify: `tests/unit/core/test_core_coverage.py`
- modify: `tests/unit/core/test_fatal_shutdown.py`
- modify: `tests/unit/core/test_logging_service.py`
- modify: `tests/unit/core/test_main.py`
- modify: `tests/unit/core/test_service_watcher_coverage.py`
- modify: `tests/unit/core/test_service_watcher_exhausted.py`
- modify: `tests/unit/core/test_web_ui_watcher.py`
- modify: `tests/unit/core/test_websocket_readiness_events.py`
- modify: `tests/unit/core/test_websocket_service_coverage.py`
- modify: `tests/unit/core/test_ws_connection_state.py`
- modify: `tests/unit/resources/lifecycle/conftest.py`
- modify: `tests/unit/resources/lifecycle/test_init.py`
- modify: `tests/unit/resources/lifecycle/test_total_timeout.py`
- modify: `tests/unit/resources/test_add_child_and_restart.py`
- modify: `tests/unit/resources/test_emit_readiness_event.py`
- modify: `tests/unit/resources/test_lifecycle_side_effect_free.py`
- modify: `tests/unit/resources/test_lifecycle_transitions.py`
- modify: `tests/unit/resources/test_restart_spec.py`
- modify: `tests/unit/resources/test_serve_wrapper_shutdown.py`
- modify: `tests/unit/resources/test_service_edge_cases.py`
- modify: `tests/unit/resources/test_service_lifecycle.py`
- modify: `tests/unit/resources/test_shutdown_edge_cases.py`
- modify: `tests/unit/resources/test_start_children_and_wait.py`
- modify: `tests/unit/scheduler/test_scheduler_error_handler.py`
- modify: `tests/unit/test_framework_injection_points.py`
- modify: `tests/unit/test_resource_depends_on.py`
- modify: `tests/unit/test_restart_spec.py`
- modify: `tests/unit/test_service_init_subclass.py`
- read: `src/hassette/resources/lifecycle.py`
- read: `src/hassette/resources/operations.py`

## Prompt

For each test file, apply the same mechanical transformation as T03:

```python
# Before
await resource.handle_failed(exc)
resource.mark_ready(reason="test")
await resource.start_children_and_wait(timeout=5)

# After
from hassette.resources.lifecycle import handle_failed, mark_ready
from hassette.resources.operations import start_children_and_wait
await handle_failed(resource, exc)
mark_ready(resource, reason="test")
await start_children_and_wait(resource, timeout=5)
```

Add imports at the top of each file. Some files were already partially migrated by T04 (spy patterns) — only fix the remaining direct method calls.

After all migrations, run `ptest -n 4` to verify the full test suite passes.

## Focus

- Files in `tests/unit/resources/` are the heaviest — they test lifecycle transitions directly and have the most call sites.
- `tests/unit/resources/lifecycle/conftest.py` likely creates test fixtures that call lifecycle methods — these become function calls.
- Some test files import from `hassette.resources` — the new function imports may coexist.
- Watch for `await resource.restart()` — `restart` moves to `operations.py`, not `lifecycle.py`.
- Watch for `resource.start_children_and_wait()` — also in `operations.py`.
- Files that appear in both T04 and this list (e.g., `test_core.py`, `test_websocket_service.py`) will already have some imports from T04 — add to the existing import statements.

## Verify

- [ ] AC#5: Full test suite passes: `ptest -n 4` exits 0 (unit + integration tests green).
