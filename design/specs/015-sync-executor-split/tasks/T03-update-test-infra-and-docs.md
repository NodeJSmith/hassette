---
task_id: "T03"
title: "Update test infrastructure, remaining tests, and docs"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["AC#3", "AC#4", "AC#5"]
---

## Summary

Update all remaining test infrastructure and test files to match the new SyncExecutor/SyncExecutorService split. This is mechanical work: rename `_sync_service` to `_sync_executor`, update imports, replace `make_sync_service()` with `make_sync_executor()`, remove mirrored patching from the test harness, and update re-exports. Also update CLAUDE.md's Architecture section to document the SyncExecutor capability class.

## Target Files

- modify: `src/hassette/test_utils/harness.py`
- modify: `src/hassette/test_utils/factories.py`
- modify: `src/hassette/test_utils/fixtures.py`
- modify: `src/hassette/test_utils/mock_hassette.py`
- modify: `src/hassette/test_utils/__init__.py`
- modify: `tests/unit/task_bucket/test_run_in_thread_context_propagation.py`
- modify: `tests/unit/task_bucket/test_run_in_thread_executor_routing.py`
- modify: `tests/unit/test_make_async_adapter_timeout.py`
- modify: `tests/unit/resources/test_task_bucket_ownership.py`
- modify: `tests/unit/core/test_hassette_lifecycle.py`
- modify: `tests/unit/app/test_app_cache.py`
- modify: `tests/integration/conftest.py`
- modify: `tests/integration/test_thread_leaked_observability.py`
- modify: `CLAUDE.md`
- read: `src/hassette/core/sync_executor.py` (import paths)
- read: `design/specs/015-sync-executor-split/design.md`

## Prompt

### 1. Update test infrastructure

**`src/hassette/test_utils/harness.py`** — Read `_start_sync_executor` (lines 701-704). This method currently mirrors the `wire_services()` post-hoc patching. After T02, the patching is no longer needed because `SyncExecutor` is wired from birth. Simplify this method: it should just `add_child(SyncExecutorService)` and assign `self.hassette._sync_executor_service`. No `task_bucket._sync_service` or `task_bucket._sync_executor` patching. Also check `_setup_loop_emulation` (lines 568-581) for any `_sync_service` references and update. Check the `DEPENDENCIES` dict (lines 56-68) and `COMPONENT_CLASS_MAP` (lines 83-89) — these reference `SyncExecutorService` by name and should stay as-is (the service class still exists).

**`src/hassette/test_utils/factories.py`** — Replace `make_sync_service()` (lines 353-374) with `make_sync_executor()`. The new factory is a simple constructor call: `SyncExecutor(max_workers=max_workers)`. No `__new__` bypass, no manual field wiring. Keep the same default `max_workers` value. Update the import from `hassette.core.sync_executor import SyncExecutor`.

**`src/hassette/test_utils/fixtures.py`** — Rename the `sync_service` fixture (lines 81-88) to `sync_executor`. Return a `SyncExecutor` instance. Update teardown to call `sync_executor.shutdown_pool(timeout=5)` instead of the old shutdown path. Update the import.

**`src/hassette/test_utils/mock_hassette.py`** — Read lines 154-158. Add `hassette.sync_executor = None` alongside the existing `hassette._sync_executor_service = None` and `hassette.sync_executor_service = None` stubs. Also add `hassette._sync_executor = None` for the private attribute that `_create_task_bucket` reads.

**`src/hassette/test_utils/__init__.py`** — Update re-exports: `make_sync_service` → `make_sync_executor`, `sync_service` → `sync_executor` (if re-exported).

### 2. Update test files

These are mechanical renames. For each file, update `_sync_service` → `_sync_executor`, `SyncExecutorService` → `SyncExecutor` (where the reference is to the capability, not the lifecycle), and `make_sync_service` → `make_sync_executor`.

**`tests/unit/task_bucket/test_run_in_thread_context_propagation.py`** — Update `_sync_service` references to `_sync_executor`. Update type hints from `SyncExecutorService` to `SyncExecutor`. Update imports.

**`tests/unit/task_bucket/test_run_in_thread_executor_routing.py`** — Same renames. This file verifies work lands on the dedicated `hassette-sync` thread pool — the behavior is unchanged, only the attribute name and type.

**`tests/unit/test_make_async_adapter_timeout.py`** — Update `bucket._sync_service = sync_service` to `bucket._sync_executor = sync_executor`. Update fixture name from `sync_service` to `sync_executor`.

**`tests/unit/resources/test_task_bucket_ownership.py`** — Check for any `_sync_service` or `SyncExecutorService` references and update.

**`tests/unit/core/test_hassette_lifecycle.py`** — Update any attribute mapping entries that reference `sync_executor_service` by name. The `("sync_executor_service", "SyncExecutorService")` mapping (line ~43) stays because the service still exists — but check for any `_sync_service` references.

**`tests/unit/app/test_app_cache.py`** — Update import `make_sync_service` → `make_sync_executor` (line 21). Update usage (lines 156-158): `svc = make_sync_executor()`, `hassette._sync_executor = svc`, `hassette.sync_executor = svc` (instead of `_sync_executor_service` and `sync_executor_service`). Note: this test sets up a mock hassette with the executor for app cache behavior — verify the attribute names match what production code reads.

**`tests/integration/conftest.py`** — Update fixture assignments. The `sync_service` fixture returns `SyncExecutor` now (renamed to `sync_executor`). Any assignment to `hassette._sync_executor_service` or `hassette.sync_executor_service` with the fixture value needs updating — the fixture no longer returns a `SyncExecutorService`.

**`tests/integration/test_thread_leaked_observability.py`** — Update `bucket._sync_service = sync_service` → `bucket._sync_executor = sync_executor`. Update any `.executor` access on the sync object — `SyncExecutor` exposes `.executor` directly.

### 3. Update documentation

**`CLAUDE.md`** — In the Architecture section, find the `SyncExecutorService` paragraph (under `src/hassette/core/sync_executor_service.py`). Add a note that `SyncExecutor` is a plain capability class in `sync_executor.py` that owns the thread pool, and `SyncExecutorService` is a thin lifecycle wrapper. Keep it brief — one sentence.

### 4. Final verification

After all changes, run `prek -a && prek pyright -a --stage pre-push` and `ptest dev` to confirm everything passes.

## Focus

- The `sync_service` fixture is used across multiple test files. Grep for `sync_service` across `tests/` and `src/hassette/test_utils/` to catch all consumers — don't rely only on the Changed Files list.
- `test_app_cache.py` sets mock hassette attributes — the attribute names must match what production code (`_create_task_bucket`, `SyncExecutorService.__init__`) reads. After T02, the factory reads `hassette._sync_executor` and the service reads `hassette.sync_executor`. Verify the mock setup matches.
- The harness `DEPENDENCIES` dict and `COMPONENT_CLASS_MAP` should NOT be renamed — they use string keys and map to `SyncExecutorService` (the class), which still exists as a Service.
- `test_service_restart_specs.py` imports `SyncExecutorService` from `hassette.core.sync_executor_service` — this import path is unchanged (the class stays in that module). No changes needed.
- `tests/integration/test_core.py` also imports `SyncExecutorService` — no changes needed (same reason).

## Verify

- [ ] AC#3: `grep -n 'task_bucket._sync' src/hassette/test_utils/harness.py` returns no hits — no mirrored patching.
- [ ] AC#4: `prek -a && prek pyright -a --stage pre-push` passes with no errors.
- [ ] AC#5: `ptest dev` (unit + integration tests) passes with no failures.
