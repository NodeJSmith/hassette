---
task_id: "T04"
title: "Migrate spy-by-reassignment test patterns"
status: "done"
depends_on: ["T01", "T03"]
implements: ["FR#7", "AC#7"]
---

## Summary

Redesign 14 test files that use spy-by-reassignment patterns (`instance.method = Mock()`) to intercept framework-internal lifecycle methods. These silently break when T06 deletes the old methods — the monkeypatch would install on the instance but the production code calls the module-level function, so the mock is never invoked. Switch each to `patch("hassette.resources.lifecycle.func")` or `patch("hassette.resources.operations.func")`.

## Target Files

- modify: `tests/unit/core/conftest.py`
- modify: `tests/unit/scheduler/test_scheduler_error_handler.py`
- modify: `tests/unit/core/test_logging_service.py`
- modify: `tests/integration/test_web_ui_watcher.py`
- modify: `tests/integration/test_websocket_service.py`
- modify: `tests/unit/core/test_web_ui_watcher.py`
- modify: `tests/unit/core/test_command_executor_pipeline.py`
- modify: `tests/unit/core/test_fatal_shutdown.py`
- modify: `tests/unit/core/test_service_watcher_coverage.py`
- modify: `tests/integration/test_fatal_shutdown.py`
- modify: `tests/integration/test_core.py`
- modify: `tests/unit/core/test_core_coverage.py`
- modify: `tests/unit/resources/lifecycle/test_force_terminal.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/test_resource_depends_on.py`
- modify: `tests/integration/test_lifecycle_propagation.py`
- read: `src/hassette/resources/lifecycle.py`
- read: `src/hassette/resources/operations.py`

## Prompt

For each of the 14 test files, find every spy-by-reassignment pattern and replace it with `unittest.mock.patch` on the module-level function. The general transformation:

```python
# Before (spy-by-reassignment — breaks post-extraction)
svc.mark_ready = MagicMock()
await svc.on_initialize()
svc.mark_ready.assert_called_once()

# After (patch the module-level function)
with patch("hassette.resources.lifecycle.mark_ready") as mock_ready:
    await svc.on_initialize()
    mock_ready.assert_called_once_with(svc, reason="initialized")
```

Note: after T03 migrated src/ call sites, production code already calls the module-level functions. The `patch()` target must match the module where the function is DEFINED (not where it's imported), which is `hassette.resources.lifecycle` or `hassette.resources.operations`.

**Per-file patterns to fix:**

| File | Line(s) | Pattern | Patch target |
|------|---------|---------|--------------|
| `conftest.py` (unit/core) | 207 | `app.mark_ready = Mock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_scheduler_error_handler.py` | 33 | `scheduler.mark_ready = MagicMock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_logging_service.py` | 65 | `svc.mark_ready = Mock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_web_ui_watcher.py` (integration) | 34 | `svc.mark_ready = MagicMock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_websocket_service.py` | 460 | `websocket_service.mark_ready = Mock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_web_ui_watcher.py` (unit) | 55 | `svc.mark_ready = MagicMock()` | `hassette.resources.lifecycle.mark_ready` |
| `test_command_executor_pipeline.py` | 621,665,700 | `executor.mark_ready = MagicMock()` (3x) | `hassette.resources.lifecycle.mark_ready` |
| `test_fatal_shutdown.py` (unit) | 29,81 | `resource.request_shutdown = Mock()` | `hassette.resources.lifecycle.request_shutdown` |
| `test_service_watcher_coverage.py` | 306,330 | `resource.request_shutdown = Mock()` | `hassette.resources.lifecycle.request_shutdown` |
| `test_fatal_shutdown.py` (integration) | multiple (9x) | `*.start = Mock()` | `hassette.resources.lifecycle.start` |
| `test_core.py` (integration) | multiple (5x) | `*.start = Mock()` | `hassette.resources.lifecycle.start` |
| `test_core_coverage.py` (unit) | multiple (3x) | `child.start = Mock()` | `hassette.resources.lifecycle.start` |
| `test_force_terminal.py` | 138 | `child.cancel = MagicMock()` | `hassette.resources.lifecycle.cancel` |
| `test_app_lifecycle_service.py` | 469 | `lifecycle_service.handle_crash = AsyncMock()` | `hassette.resources.lifecycle.handle_crash` |

For each file, carefully inspect what the spy was testing:
- If it was asserting the method WAS called → use `patch()` and assert on the mock
- If it was stubbing to PREVENT a side effect → use `patch()` with a no-op or specific return value
- If it was stubbing to INJECT a side effect → use `patch(side_effect=...)`

After fixing all patterns, run the affected test files to verify they pass.

## Focus

- `conftest.py:make_mock_app_instance` (line 207) creates a full `AsyncMock` App. The `mark_ready = Mock()` there sets up the mock's attribute. After extraction, tests that verify `mark_ready` was called should patch `hassette.resources.lifecycle.mark_ready` instead. Remove the `app.mark_ready = Mock()` line from the factory and patch at the test call site.
- `test_fatal_shutdown.py` exists in BOTH `tests/unit/core/` and `tests/integration/` — different files, different patterns. Don't conflate them.
- `test_check_internal_patches.py` (tests/unit/tools/) also sets `.mark_ready = Mock()` but this tests the linter itself — it uses literal source-string fixtures, not real spy interception. Out of scope for this task.
- Some files may have BOTH spy patterns AND direct method calls. Fix only the spy patterns here; direct method calls are handled in T05.
- After patching, assertions may need updating: `svc.mark_ready.assert_called_once()` becomes `mock_ready.assert_called_once_with(svc, reason=...)` — the first argument is now the resource instance.
- **Run the AC#7 grep early** (before committing) and triage every hit. The 14-file target list drifted three times during planning and may still be incomplete. Filter false positives like `Subscription.cancel`, `task.cancel`, and linter-test fixtures that use literal source strings.

## Verify

- [ ] FR#7: All 14 spy-by-reassignment test files use `patch()` on module-level functions. Verify: `ptest -n 4 tests/unit/core/conftest.py tests/unit/scheduler/test_scheduler_error_handler.py tests/unit/core/test_logging_service.py tests/integration/test_web_ui_watcher.py tests/integration/test_websocket_service.py tests/unit/core/test_web_ui_watcher.py tests/unit/core/test_command_executor_pipeline.py tests/unit/core/test_fatal_shutdown.py tests/unit/core/test_service_watcher_coverage.py tests/integration/test_fatal_shutdown.py tests/integration/test_core.py tests/unit/core/test_core_coverage.py tests/unit/resources/lifecycle/test_force_terminal.py tests/unit/core/test_app_lifecycle_service.py` all pass.
- [ ] AC#7: `grep -rn '\.handle_failed\s*=\|\.mark_ready\s*=\|\.handle_crash\s*=\|\.handle_stop\s*=\|\.handle_starting\s*=\|\.handle_running\s*=\|\.mark_not_ready\s*=\|\.request_shutdown\s*=\|\.create_service_status_event\s*=\|\.start\s*=.*Mock\|\.cancel\s*=.*Mock' tests/` returns no results for the extracted methods (filter false positives like `Subscription.cancel` or `task.cancel`).
