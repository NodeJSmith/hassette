---
task_id: "T01"
title: "Add interruptible thread-pool executor primitive"
status: "done"
depends_on: []
implements: ["FR#6", "FR#7"]
---

## Summary
Port Home Assistant's `async_raise` and `InterruptibleThreadPoolExecutor` into a new Hassette module, adapting the shutdown join/interrupt loop to take a configurable `timeout` parameter instead of HA's hard-coded module constant. This is the low-level primitive the `SyncExecutorService` will own — it knows nothing about Hassette services, so it can be unit-tested in isolation. It is the riskiest code in the feature (CPython `ctypes` interpreter internals), so it ships with focused tests for interrupt success, race suppression, and the C-block limit.

## Prompt
Create `src/hassette/task_bucket/interruptible_executor.py` containing:

1. **`async_raise(tid: int, exctype: type[BaseException]) -> None`** — port verbatim from `/home/jessica/source/core/homeassistant/util/thread.py:38-55`:
   - Validate `exctype` is a class (`inspect.isclass`), raise `TypeError` otherwise.
   - Call `ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(exctype))`.
   - `res == 1`: success, return. `res == 0`: raise `ValueError("Thread not found")`. `res > 1`: revert with `PyThreadState_SetAsyncExc(c_tid, None)` then raise `SystemError`.

2. **`InterruptibleThreadPoolExecutor(ThreadPoolExecutor)`** — port from `/home/jessica/source/core/homeassistant/util/executor.py:61-101`, with one adaptation: the join/interrupt budget must be a **parameter**, not the module-level `EXECUTOR_SHUTDOWN_TIMEOUT` constant. Specifically:
   - `shutdown(self, *args, join_threads_or_timeout: bool = True, timeout: float = <default>, **kwargs)` calls `super().shutdown(wait=False, cancel_futures=True)` then `self.join_threads_or_timeout(timeout)` if requested.
   - `join_threads_or_timeout(self, timeout: float)` runs the join-or-interrupt loop bounded by `timeout` (replacing HA's `EXECUTOR_SHUTDOWN_TIMEOUT` reads at `executor.py:81,96`).
   - `join_or_interrupt_threads(threads, per_attempt_timeout, log)` joins each thread within its slice, logs the straggler's name+stack via a helper equivalent to HA's `_log_thread_running_at_shutdown` (`executor.py:23-32`), then `async_raise(thread.ident, SystemExit)` wrapped in `contextlib.suppress(SystemError, ValueError)`.

Keep the module free of any Hassette imports — it is a standalone primitive. Use the project's logging convention (`logging.getLogger(__name__)`).

Add unit tests at `tests/unit/task_bucket/test_interruptible_executor.py` (create the directory if needed). Run them with `uv run pytest tests/unit/task_bucket/test_interruptible_executor.py -v` (NEVER `-n auto`).

## Focus
- HA reference files are at `/home/jessica/source/core/homeassistant/util/thread.py` and `/home/jessica/source/core/homeassistant/util/executor.py` — read them directly; do not reconstruct from memory.
- The ONLY deviation from a verbatim port is parameterizing the timeout. Everything else (the `res` handling, the `is_alive()`/`ident is None` guard, the `SystemError`/`ValueError` suppression) is ported as-is.
- `async_raise`'s `res == 0` path raises `ValueError`. The suppression in `join_or_interrupt_threads` swallows it intentionally (a thread that vanished before the raise landed is already gone) — this is correct, not a swallowed error. Document with a one-line comment.
- C-blocked threads (`time.sleep`, `socket.recv`) cannot be interrupted by `async_raise` until they return to Python. The join loop must abandon them when the budget expires, not hang. Test this explicitly.
- `thread_name_prefix` is set by the *caller* (T03), not hard-coded here.

## Verify
- [ ] FR#6: `async_raise(tid, SystemExit)` against a thread running a pure-Python busy loop terminates it; a straggler's name and stack are logged before the interrupt (assert via caplog).
- [ ] FR#7: `join_threads_or_timeout(timeout)` completes within the passed `timeout` even when a worker is blocked in a C call (`time.sleep`) that never joins; `res == 0` and `res > 1` paths are handled (ValueError suppressed; SystemError revert path covered) and no exception propagates out of the shutdown call.
