---
task_id: "T01"
title: "Extract SyncExecutor capability class"
status: "done"
depends_on: []
implements: ["FR#1", "AC#6"]
---

## Summary

Create a new `SyncExecutor` class in `src/hassette/core/sync_executor.py` that owns the thread pool and `submit()` capability. This is a purely additive step — the new class exists alongside the current `SyncExecutorService`, which still works as-is. Move the capability methods, saturation state, `SyncWorkerHandle`, `SYNC_WORKER_HANDLE`, and constants from `sync_executor_service.py` to the new file. Add `rebuild_pool()` and `shutdown_pool()` methods for lifecycle delegation. Adapt the saturation tests to construct `SyncExecutor` directly. Do NOT modify `tests/unit/conftest.py` helpers in this task — they are consumed by `test_sync_executor_service_wiring.py` which is not updated until T02.

## Target Files

- create: `src/hassette/core/sync_executor.py`
- read: `src/hassette/core/sync_executor_service.py`
- modify: `tests/unit/test_sync_executor_service_saturation.py`
- read: `src/hassette/bus/router.py` (convention reference)
- read: `design/specs/015-sync-executor-split/design.md`

## Prompt

Create `src/hassette/core/sync_executor.py` with a plain `SyncExecutor` class following the Router/AppRegistry pattern (no Resource/Service base class).

**Move from `sync_executor_service.py`** (read lines 40-78 and 91-214 for the source):
- Module-level: `SyncWorkerHandle` dataclass, `SYNC_WORKER_HANDLE` contextvar, `SYNC_EXECUTOR_THREAD_NAME_PREFIX` constant, saturation constants (`_SATURATION_WARN_THRESHOLD`, `_SATURATION_WARN_RATE_LIMIT_SECS`, `_SATURATION_PROBE_INTERVAL_SECS`)
- Instance methods: `submit()`, `track_submission()`, `log_saturation_rate_limited()`
- Instance state: `executor`, `_active_workers`, `_last_saturation_warn_ts`

**Add new methods:**
- `rebuild_pool(max_workers: int, thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX) -> None` — creates a fresh `InterruptibleThreadPoolExecutor`, resets `_active_workers` and `_last_saturation_warn_ts`. Does not shut down the old pool (the caller — `SyncExecutorService.on_initialize()` via `restart()` — handles shutdown before calling this).
- `shutdown_pool(timeout: float) -> None` — calls `self.executor.shutdown(timeout=timeout)`

**Constructor:** `SyncExecutor(max_workers: int, thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX)` — builds the `InterruptibleThreadPoolExecutor` immediately, initializes `_active_workers = 0` and `_last_saturation_warn_ts = 0.0`. Add a `logger` attribute.

**Do NOT modify `sync_executor_service.py` in this task** — that happens in T02. The current `SyncExecutorService` continues to work as-is. This task is purely additive.

**Do NOT modify `tests/unit/conftest.py`** — the `make_service`, `make_sync_executor_config`, and `make_sync_executor_hassette` helpers are still imported by `test_sync_executor_service_wiring.py` (not touched until T02). Removing them here would break that test file's imports. The conftest helpers are updated in T02 alongside the wiring test.

**Update `tests/unit/test_sync_executor_service_saturation.py`** (687 lines): This file tests saturation monitoring behavior that moves to `SyncExecutor`. Update imports and test setup to construct `SyncExecutor` directly instead of `SyncExecutorService` via the conftest helper. The tests exercise `log_saturation_rate_limited()`, `track_submission()`, `_active_workers`, and saturation thresholds — all of which are now on `SyncExecutor`. Method signatures and behavior are unchanged; only the construction path changes. Tests that reference `self.executor` on the service need updating to reference the `SyncExecutor` instance directly. Tests that exercise shutdown behavior or `serve()` loop remain on `SyncExecutorService` and will be updated in T02.

## Focus

- `SyncExecutor` must be fully functional standalone — `SyncExecutor(max_workers=2)` followed by `executor.submit(fn)` must work. This is what makes it testable without lifecycle machinery.
- `submit()` captures `copy_context()` and wraps with `SyncWorkerHandle` — preserve this behavior exactly from `sync_executor_service.py:129-158`.
- `log_saturation_rate_limited()` reads `self.executor._max_workers` and `self.executor._work_queue.qsize()` (private CPython attributes). Keep the existing `pyright: ignore` suppression comments.
- The `InterruptibleThreadPoolExecutor` import comes from `src/hassette/task_bucket/interruptible_executor.py`.
- The saturation test file has parametrized tests with `make_service()` from conftest. Only update call sites in test classes that exercise **capability** behavior (saturation thresholds, submit, active workers). Leave test classes that exercise **lifecycle** behavior (shutdown, serve loop, config) untouched — those construct `SyncExecutorService` and are updated in T02 alongside the conftest helper replacement.

## Verify

- [ ] FR#1: `SyncExecutor` is a plain class with no `Resource`/`Service` in its MRO. It exposes `submit(fn, *args, **kwargs) -> asyncio.Future` with context propagation and `SyncWorkerHandle` attribution.
- [ ] AC#6: `grep -rn 'class SyncExecutor' src/hassette/core/sync_executor.py` confirms the class exists without `Resource`/`Service` base.
