---
task_id: "T04"
title: "Route sync user code through the dedicated executor"
status: "planned"
depends_on: ["T03"]
implements: ["FR#1", "FR#2", "FR#9", "AC#2", "AC#7"]
---

## Summary
Reroute `TaskBucket.run_in_thread` from asyncio's loop-default executor to `hassette.sync_executor`, so every sync handler, sync job, and App sync lifecycle hook runs on the dedicated pool while framework-internal `asyncio.to_thread` calls (logging, database) stay on the default pool. While doing so, capture the worker thread that runs each call (via a ContextVar or closure cell) so the observability check in T06 can ask whether that thread outlived its timeout. The caller-visible timeout signal must be unchanged.

## Prompt
1. **Edit `src/hassette/task_bucket/task_bucket.py`, `run_in_thread` (`:153-176`).** Currently it returns `asyncio.to_thread(_call)` (`:176`). Change it to submit `_call` to the dedicated executor: `loop = asyncio.get_running_loop(); return loop.run_in_executor(self.hassette.sync_executor, _call)` (or await it inside an `async def` wrapper to preserve the current return contract — match the existing call sites in `make_async_adapter` at `:205` and `app.py:152-177`). Keep the existing `ctx.use_task_bucket(current_bucket)` context preservation inside `_call`.

2. **Capture the worker thread identity via a shared mutable cell** — NOT a ContextVar. Create `cell: list[threading.Thread | None] = [None]` inside `run_in_thread`, set `cell[0] = threading.current_thread()` as the first statement of `_call` (on the worker), and expose `cell` to the caller (e.g. return it alongside the awaitable, or stash it where `command_executor._execute` can read it for the execution in flight — see Focus). The reader checks `cell[0]` and `is_alive()` at the timeout site (T06 consumes it). **Do not use a `ContextVar`**: `loop.run_in_executor` copies the loop thread's context into the worker callable, so a value the worker writes to a ContextVar mutates the worker's own copy and the loop thread reads back `None` — the leak check would silently never fire. The cell stays `[None]` until `_call` actually starts running, so a timeout that fires before the worker dequeues the job leaves it unset — that is a "not-started" timeout, not a leak; T06 relies on this.

3. **Leave `make_async_adapter` (`:187-213`) structurally intact** — it already re-raises `TimeoutError` ahead of its broad `except Exception` (`:206-209`); that stays correct. The `task_bucket.py:209` comment ("no task to cancel anymore") remains accurate.

4. **Do NOT touch** the `asyncio.to_thread` calls in `logging_service.py`, `database_service.py`, or `task_bucket.run_sync`/`run_on_loop_thread` — those framework-internal calls must keep using the default pool.

Add/adapt tests:
- A test asserting sync user code runs on the dedicated pool (assert the worker thread's name starts with `hassette-sync`) while a framework `asyncio.to_thread` call runs on a default-pool thread (no `hassette-sync` prefix).
- A test asserting the timeout signal is unchanged: a slow sync handler under a short timeout still surfaces `TimeoutError`/`status='timed_out'` to the caller with the existing WARNING.
- Adapt `tests/unit/test_make_async_adapter_timeout.py` — its `hassette` stub sets `_loop_thread_id = None`; it must now provide `hassette.sync_executor` (a real `InterruptibleThreadPoolExecutor` or the service) since `run_in_thread` submits there instead of `asyncio.to_thread`. Confirm `TimeoutError` still propagates cleanly.
- Update the harness stubs as needed: `src/hassette/test_utils/helpers.py` (the `make_async_adapter` identity stub at `:451` can stay for tests that don't exercise the executor) and any `create_hassette_stub()`/`HassetteHarness` setup so tests reaching `run_in_thread` have a `sync_executor`.

Run affected files with `uv run pytest <files> -v` (never `-n auto`).

## Focus
- `run_in_thread` is the single seam: its only callers are user sync code (App sync hooks at `app.py:152-177`, and `make_async_adapter` used by `listeners.py:712`, `scheduler_service.py:320`, `command_executor.py:534`). Framework internals call `asyncio.to_thread` directly, so they are unaffected — verify this distinction holds before changing routing.
- `loop.run_in_executor` returns an awaitable; preserve the exact return/await semantics `make_async_adapter` and the App hooks expect (they `await self.run_in_thread(...)`).
- The capture mechanism is a shared mutable cell (`list[threading.Thread | None]`), set on the *worker* thread inside `_call` and read on the *loop* thread at the timeout site. A `ContextVar` is the wrong tool — writes inside the worker callable do not propagate back to the loop thread's context (verified: the loop reads back `None`). The cell must be reachable by `command_executor._execute` for the execution currently in flight; the cleanest wiring is for the make_async_adapter/`_execute` path to hold the cell for the call it is timing. Document the exact wiring so T06 reads the same cell.
- Behavioral invariant: the caller-visible timeout contract (await unblocks, `status='timed_out'`, existing WARNING) must not change.

## Verify
- [ ] FR#1: sync user code submitted through `run_in_thread` executes on the dedicated executor (worker thread name prefixed `hassette-sync`).
- [ ] FR#2: a framework-internal `asyncio.to_thread` call still runs on the loop-default pool (not `hassette-sync`).
- [ ] FR#9: a timed-out sync handler still surfaces the unchanged signal — caller unblocks, `status='timed_out'` recorded, existing WARNING logged.
- [ ] AC#2: a single test demonstrates the pool split (sync user code on dedicated, framework `to_thread` on default) by thread identity.
- [ ] AC#7: the caller-visible timeout signal is verified unchanged against the pre-change behavior.
