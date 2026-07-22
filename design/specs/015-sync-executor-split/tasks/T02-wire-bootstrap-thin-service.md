---
task_id: "T02"
title: "Wire bootstrap and thin SyncExecutorService"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "AC#1", "AC#2", "AC#7"]
---

## Summary

This is the core swap. Construct `SyncExecutor` in `Hassette.__init__` before `super().__init__()`, thin `SyncExecutorService` to a lifecycle-only wrapper that delegates to `SyncExecutor`, update `TaskBucket` to use `_sync_executor` instead of `_sync_service`, and fix the `command_executor.py` import path. All three workarounds are eliminated in this task. The wiring tests are updated to verify the new structure.

## Target Files

- modify: `src/hassette/core/core.py`
- modify: `src/hassette/core/sync_executor_service.py`
- modify: `src/hassette/task_bucket/task_bucket.py`
- modify: `src/hassette/core/command_executor.py`
- modify: `tests/unit/test_sync_executor_service_wiring.py`
- modify: `tests/unit/test_sync_executor_service_saturation.py`
- modify: `tests/unit/conftest.py`
- read: `src/hassette/core/sync_executor.py` (created in T01)
- read: `src/hassette/resources/base.py` (Resource.__init__ reference)
- read: `design/specs/015-sync-executor-split/design.md`

## Prompt

### 1. Modify `src/hassette/core/core.py`

**In `Hassette.__init__`** (read lines 86-136):
- Before `super().__init__()` (currently line 94), add: `self._sync_executor = SyncExecutor(config.lifecycle.sync_executor_max_workers)` with the import from `hassette.core.sync_executor`.
- After `super().__init__()`, add: `self.task_bucket._sync_executor = self._sync_executor` — this wires Hassette's own TaskBucket (which bypasses the factory because it's passed explicitly as `task_bucket=TaskBucket(self, parent=self)`).
- Change `self._sync_executor_service: SyncExecutorService | None = None` (line 100) — keep this slot, it's still used.

**In `wire_services()`** (read lines 168-257):
- Keep `self._sync_executor_service = self.add_child(SyncExecutorService)` (line 188).
- **Delete** the post-hoc patching block (lines 190-193): the two lines that patch `self.task_bucket._sync_service` and `self._sync_executor_service.task_bucket._sync_service`, plus the comment above them. These are no longer needed.
- The "MUST be the first add_child" ordering comment (lines 185-187) can be relaxed or removed — `SyncExecutorService` no longer needs to be first because the factory reads `hassette._sync_executor` (set in `__init__`), not `hassette.sync_executor_service` (set in `wire_services()`).

**Add a `sync_executor` plain attribute** — expose `self._sync_executor` as a public attribute. Since it's set in `__init__` (always available), a plain attribute is correct — no property, no guard. This differs from the existing `@property` convention for service accessors because those need guards (they're wired later in `wire_services()`). `sync_executor` is set in `__init__` and is always available.

### 2. Modify `src/hassette/core/sync_executor_service.py`

Thin this to a lifecycle-only wrapper. Read the current file (275 lines) and T01's `sync_executor.py` for context.

- **Remove** all capability methods that moved to `SyncExecutor` in T01: `submit()`, `track_submission()`, `log_saturation_rate_limited()`. Remove `_active_workers`, `_last_saturation_warn_ts` instance state. Remove `SyncWorkerHandle`, `SYNC_WORKER_HANDLE`, `SYNC_EXECUTOR_THREAD_NAME_PREFIX`, and saturation constants (already in `sync_executor.py`).
- **In `__init__`**: Read `self.sync_executor = hassette.sync_executor` (the pre-built capability from `Hassette.__init__`). Remove counter initialization.
- **In `on_initialize()`**: Replace `self.executor = InterruptibleThreadPoolExecutor(...)` with `self.sync_executor.rebuild_pool(config.lifecycle.sync_executor_max_workers, SYNC_EXECUTOR_THREAD_NAME_PREFIX)`. Import `SYNC_EXECUTOR_THREAD_NAME_PREFIX` from `hassette.core.sync_executor`.
- **In `serve()`**: Keep `mark_ready()` and the probe loop structure. Replace the inline saturation check with `self.sync_executor.log_saturation_rate_limited()`.
- **In `on_shutdown()`**: **Remove** the `if not hasattr(self, "executor"): return` guard — after the split, `SyncExecutorService` never sets `self.executor` (it lives on `self.sync_executor.executor`), so this guard would always return True, silently turning `on_shutdown()` into a no-op. The guard is no longer needed because `self.sync_executor` and its pool are always present. Replace `self.executor.shutdown(timeout=budget)` with `self.sync_executor.shutdown_pool(budget)`. The `asyncio.to_thread` wrapper stays.
- **Keep**: `depends_on = []`, `restart_spec = CORE_PERMANENT_RESTART`, the class-level docstring, and the Service/lifecycle contract.

### 3. Modify `src/hassette/task_bucket/task_bucket.py`

Read the current file (390 lines).

- **Rename** `_sync_service` to `_sync_executor` throughout the file. Update the type annotation from `SyncExecutorService | None` to `SyncExecutor | None`. Add the import for `SyncExecutor` from `hassette.core.sync_executor`.
- **In `run_in_thread()`** (lines 170-195): Update the attribute name in the None check and the `submit()` call.
- **Simplify `_create_task_bucket()`** (lines 380-386): Remove the `contextlib.suppress(RuntimeError)` and the try/except. Replace with:
  ```python
  def _create_task_bucket(hassette: "Hassette", owner: "Resource") -> "TaskBucket":
      bucket = TaskBucket(hassette, parent=owner)
      bucket._sync_executor = hassette._sync_executor
      return bucket
  ```
  No exception suppression, no conditional. `hassette._sync_executor` is always available because it's set in `Hassette.__init__` before any Resource is constructed.

### 4. Modify `src/hassette/core/command_executor.py`

- Update the import (line 26): change `from hassette.core.sync_executor_service import SYNC_WORKER_HANDLE` to `from hassette.core.sync_executor import SYNC_WORKER_HANDLE`.

### 5. Update `tests/unit/conftest.py`

Replace `make_sync_executor_config`, `make_sync_executor_hassette`, and `make_service` helpers (lines 48-76) with a simpler helper that constructs `SyncExecutor(max_workers=N)` directly. These helpers are consumed by `test_sync_executor_service_wiring.py` and `test_sync_executor_service_saturation.py` — both are updated in this task, so the rename is safe.

### 6. Update `tests/unit/test_sync_executor_service_wiring.py`

Read the current file (287 lines). This file tests:
- Class attributes (`depends_on`, `restart_spec`) — stay on `SyncExecutorService`, keep as-is
- Executor built in `on_initialize` — stays on `SyncExecutorService` (via `rebuild_pool`), adapt
- Restart rebuilds pool — stays on `SyncExecutorService`, adapt to verify `SyncExecutor.rebuild_pool()` is called
- Dependency-graph acyclicity — stays, keep as-is
- `wire_services()` registration — adapt: `hassette.sync_executor` is now set in `__init__`, not `wire_services()`
- Post-hoc patched TaskBuckets — **replace** with stronger assertion: all TaskBuckets have `_sync_executor` set from birth (TC#2 from design)
- Shutdown ordering — stays, keep as-is

**Specific renames in this file:**
- All `svc.executor` references (~15 sites) change to `svc.sync_executor.executor` — the executor attribute now lives on `SyncExecutor`, not `SyncExecutorService`.
- Line 72: `assert not hasattr(svc, "executor")` currently tests "executor doesn't exist until on_initialize runs." After the split, `svc.executor` never exists (it's `svc.sync_executor.executor`), so this assertion becomes vacuously true. Replace it with a meaningful assertion about the `SyncExecutor`'s pool state before/after `on_initialize`.

**Docstring/error message updates in `task_bucket.py`:**
- `run_in_thread()`'s docstring references `SyncExecutorService.submit` — update to `SyncExecutor.submit`.
- `run_in_thread()`'s `RuntimeError` message references `SyncExecutorService` and `_sync_service` — update to `SyncExecutor` and `_sync_executor`.

### 7. Update lifecycle tests in `tests/unit/test_sync_executor_service_saturation.py`

T01 updates the capability tests in this file (saturation monitoring, threshold checks) to use `SyncExecutor` directly. But this file also contains lifecycle tests that construct `SyncExecutorService` via `make_service()`/`make_sync_executor_hassette()` from conftest — and this task (T02) replaces those conftest helpers. These lifecycle tests must be updated here to avoid breaking:

- `TestOnShutdown` (lines 57-82) — tests `svc.on_shutdown()` and `svc.executor.shutdown()`. Update to use the thinned `SyncExecutorService` with its `SyncExecutor`. `test_on_shutdown_skips_when_executor_not_initialized` (line 78) tests the `hasattr(self, "executor")` guard that this task deletes — **remove or rewrite this test** since the guard no longer exists (the pool is always present via `SyncExecutor`).
- `TestPeriodicSaturationProbe` (lines 272-371) — tests the `serve()` probe loop. Update to construct a real `SyncExecutorService` that wraps a `SyncExecutor`, or mock appropriately.
- `TestShutdownInterruptsPythonWorker` and `TestShutdownCBlockedWorker` (lines 374+, 484+) — shutdown-under-load tests. Update `svc.executor` references to `svc.sync_executor.executor`.
- `TestConfigBehavior` (lines 571-621) — tests config-driven max_workers/shutdown_timeout. Update construction from `make_service()` to use `SyncExecutor` + `SyncExecutorService`.

Add new tests:
- **TC#1**: `hassette.sync_executor` is a `SyncExecutor` instance immediately after `Hassette.__init__()`, before `wire_services()`.
- **TC#2**: Every TaskBucket created by the factory has `_sync_executor` set (non-None) from birth.
- **TC#3**: After `SyncExecutorService` restart, `SyncExecutor` object identity is preserved but the pool is fresh.

## Focus

- The bootstrap ordering in `core.py` is load-bearing. `self._sync_executor = SyncExecutor(...)` MUST come before `super().__init__()` (which triggers `TaskBucket` construction). `self.task_bucket._sync_executor = self._sync_executor` MUST come after.
- `_create_task_bucket` reads `hassette._sync_executor` (the private attribute, not a property) — this avoids any guard or error. The attribute is set in `__init__`, so it's always present when the factory runs.
- `depends_on` declarations on BusService, SchedulerService, and AppHandler MUST remain unchanged — they reference `SyncExecutorService` (the class), which still exists. Grep to confirm after changes.
- `command_executor.py` only reads the `SYNC_WORKER_HANDLE` contextvar — the import path is the only change.
- The `sync_executor_service` property with the `_service_not_wired_error` guard stays unchanged.
- After this task, `prek -a` and `prek pyright -a --stage pre-push` should pass (type checking will catch mismatched attribute names).

## Verify

- [ ] FR#2: `SyncExecutor` is constructed in `Hassette.__init__()` before `super().__init__()` and is available to every TaskBucket from birth.
- [ ] FR#3: `SyncExecutorService` remains a `Service` subclass wrapping `SyncExecutor` for lifecycle: `on_initialize()` calls `rebuild_pool()`, `serve()` probes saturation, `on_shutdown()` calls `shutdown_pool()`.
- [ ] FR#4: `TaskBucket.run_in_thread()` delegates to `SyncExecutor.submit()`.
- [ ] FR#5: `SyncExecutorService.on_initialize()` calls `SyncExecutor.rebuild_pool()` for restart-in-place, preserving object identity.
- [ ] FR#6: Every TaskBucket has `_sync_executor` set from birth — no exception suppression, no post-hoc patching.
- [ ] FR#7: `depends_on` declarations on BusService, SchedulerService, and AppHandler remain unchanged.
- [ ] AC#1: `grep -rn 'contextlib.suppress(RuntimeError)' src/hassette/task_bucket/task_bucket.py` returns no hits — the factory's RuntimeError suppression is gone.
- [ ] AC#2: `sed -n '/def wire_services/,/^    def /p' src/hassette/core/core.py | grep -c 'task_bucket._sync'` returns `0` — no post-hoc patching in `wire_services()`.
- [ ] AC#7: `grep -l 'SyncExecutorService' src/hassette/core/bus_service.py src/hassette/core/scheduler_service.py src/hassette/core/app_handler.py` returns all three files.
