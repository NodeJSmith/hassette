# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: `_reload_app_or_changed_instances` exceeds the 50-line structural-messiness threshold

Status: resolved — fixed during known issues walkthrough
Run: 116
Source: clean-code
Reason not fixed now: behavior-change
Observed in: src/hassette/core/app_lifecycle_service.py:918-975
Affected files:
- src/hassette/core/app_lifecycle_service.py

Issue:
`AppLifecycleService._reload_app_or_changed_instances()` is ~58 lines (including its docstring
and inline rationale comments), over the nitpicker style guide's 50-line-per-function threshold.
It handles three responsibilities in one body: the missing-manifest fallback, the instance-count
fallback, and the concurrent per-index batch reload (with a nested `_reload_one` closure and a
single shared lock acquisition).

Why deferred:
The function is new in this PR and is exercised by a dedicated, carefully-constructed test class
(`TestApplyChangesPerInstanceRestart` in `tests/unit/core/test_app_lifecycle_service_operations.py`),
including a deterministic concurrency test
(`test_batch_reload_runs_instances_concurrently_not_sequentially`) that proves the batch reload
runs under a single lock acquisition rather than serially. Splitting the function now — e.g.
separating the two fallback checks from the batch-reload body — risks subtly changing where the
lock is acquired relative to the fallback checks, which the design doc's Key Constraints section
calls out as safety-critical (`reload_instance` must never use a per-instance lock, only the
per-app-key lock). This is exactly the kind of restructuring `refactoring-discipline.md` says
needs a pin-test-first treatment before touching structure, which is out of scope for a
mechanical clean-code pass.

Recommended follow-up:
Extract the per-index batch-reload body (from `self.logger.debug("Reloading changed instance(s)...")`
through the final `async with ... gather(...)` call) into a separate private helper (e.g.
`_reload_changed_indices(app_key, changed_indices)`), leaving `_reload_app_or_changed_instances`
to own only the two fallback decisions and delegate the batch case. Add/keep the existing
concurrency test passing unchanged as the pin.

Acceptance criteria:
- `_reload_app_or_changed_instances` is under 50 lines.
- The extracted helper is under 50 lines.
- `TestApplyChangesPerInstanceRestart` (all cases, including the concurrency proof) still passes
  unmodified against the new structure.

## ~~KI-002~~ (resolved)

Fixed by the orchestrator after the clean-code dispatch: added
`mock_hassette._app_handler.registry.get_instances.return_value = {}` to
`test_nonexistent_app_key_returns_404` in `tests/integration/web_api/test_validation.py`.
All 3 parametrized cases now pass.
