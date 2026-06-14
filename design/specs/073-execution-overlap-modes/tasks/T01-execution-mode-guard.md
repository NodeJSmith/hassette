---
task_id: "T01"
title: "Add ExecutionMode enum and ExecutionModeGuard with unit tests"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "FR#9", "FR#10", "FR#11", "FR#13", "FR#15", "FR#17", "AC#5", "AC#12"]
---

## Summary

Build the shared foundation: the `ExecutionMode` StrEnum and the `ExecutionModeGuard` that owns the four-mode overlap state machine. The guard is overlap-only, does no I/O, and is reused unchanged by the scheduler follow-up (#1027). This task delivers the guard plus a full unit-test suite proving each mode's semantics and race-safety. No bus/scheduler wiring yet — that is T02.

## Prompt

Implement two new pieces, with unit tests.

1. **`ExecutionMode` enum** — add to `src/hassette/types/enums.py`, beside `RestartType` (line 18). A `StrEnum` with exactly four members: `SINGLE = "single"`, `RESTART = "restart"`, `QUEUED = "queued"`, `PARALLEL = "parallel"` (FR#1). Export it wherever the other enums in this module are exported (check `src/hassette/types/__init__.py` and any `hassette` top-level re-exports of `RestartType`).

2. **`ExecutionModeGuard`** — new module `src/hassette/execution_mode.py`. One instance per listener. It owns the four-mode state machine and nothing else (no events, no jobs, no telemetry, no HA, no DB). Define a module constant `DEFAULT_QUEUE_DEPTH = 10` at the top.

   State it holds:
   - the current handler `asyncio.Task | None`
   - a bounded `collections.deque` of pending invocation factories (for `queued`), max length = the cap
   - a single `asyncio.Lock`
   - two integer counters: `suppressed` and `dropped`

   Constructor takes `mode: ExecutionMode` and `cap: int = DEFAULT_QUEUE_DEPTH` (the cap is a constructor arg so a future `max` overrides it with no shape change — do NOT add a public `max` parameter anywhere).

   The async entry point takes a "run-and-track" callable — a `Callable[[], asyncio.Task]` supplied by the caller — that spawns a fresh child task for one handler invocation through the caller's own task machinery (in the bus, the caller spawns it via `task_bucket`; see T02). The guard must NOT create a detached task itself: it only decides whether/when to call the supplied callable, retains the returned task as the cancellable handle, and `await`s it. Note for the caller's benefit (do not assume it here): the handler is currently run *inline* inside the per-dispatch task, so this child task is new structure — T02 wires it so the outer dispatch task stays pending while the child runs, keeping the drain accounting correct. Under the internal lock, apply the mode:
   - **`single`**: if a tracked task is running, increment `suppressed`, log at DEBUG, return a `Suppressed` outcome (FR#4, FR#5). Else call run-and-track, store the task, return `Ran`.
   - **`restart`**: if a tracked task is running, cancel it and `await` its settling (swallowing `CancelledError` from the cancelled task) — all while still holding the lock so no third trigger interleaves (FR#13) — then call run-and-track for the new invocation (FR#6, FR#7).
   - **`queued`**: if a tracked task is running, append the factory to the deque; if the deque is already at cap, increment `dropped`, log at DEBUG, return `Dropped` and do NOT evict an existing item (newest-dropped) (FR#9, FR#10). Else call run-and-track; when the running task completes, drain the next factory from the deque and run it (one at a time, in order) (FR#8).
   - **`parallel`**: call run-and-track without tracking or locking overhead — a pass-through (FR#11).

   Return an outcome value (e.g. an enum or small dataclass: `Ran` / `Suppressed` / `Dropped`) so the caller can read counts (the guard also keeps `suppressed`/`dropped` as live attributes for the snapshot in T03) (FR#15).

   Add a `release()` method, for use when a listener is cancelled/re-registered: it cancels the tracked task (if any) and clears the deque so that pending `queued` factories are dropped rather than run, with no references retained — including when called mid-drain (FR#17).

3. **Unit tests** — new `tests/unit/bus/test_execution_mode_guard.py` (the existing `tests/unit/bus/test_handler_invoker.py` is the sibling pattern to follow for async test structure and fixtures). Use an `asyncio.Event` gate to hold a tracked invocation "running" while firing further triggers (the startup-race pattern in CLAUDE.md / the project's `tests/` conventions). Cover:
   - `single`: second trigger while first runs → exactly one run, `suppressed == 1` (FR#4, FR#5)
   - `restart`: second trigger cancels first (assert the first sees `CancelledError`), second runs to completion, no exception escapes (FR#6, FR#7)
   - `restart` A→B→C in tight succession against a gated handler → never two concurrent running invocations at any settle point (assert via a "currently running" counter that never exceeds 1) (FR#13, AC#5)
   - `queued`: N triggers during a gated run → all N run in arrival order after the first completes (FR#8)
   - `queued` at cap: extra trigger dropped (newest), existing queue preserved, `dropped` incremented (FR#9, FR#10)
   - `parallel`: M triggers during a gated run → M concurrent runs (FR#11)
   - `release()`: clears a running task + pending queue; pending factories do not run; no leaked references (FR#17, AC#12)

Run the new test file and confirm it passes before finishing.

## Focus

- `src/hassette/types/enums.py` — `RestartType` at line 18, `ResourceStatus` at 97; follow the `StrEnum` style there. Check `src/hassette/types/__init__.py` for the export list.
- The guard is consumed at the bus chokepoint `HandlerInvoker.dispatch` (`src/hassette/bus/listeners.py:192`) in T02 — keep the entry-point signature ergonomic for that call site (it already has an `invoke_fn` and a `task_bucket`). The "run-and-track" callable is how the guard stays out of the spawn business while keeping the handler task visible to the bus's `_dispatch_pending` drain.
- Single event loop, single thread: the lock is for ordering across concurrently-spawned dispatch tasks, not OS threads. The check-and-set within a single non-`await` span is already safe; the lock matters specifically across the `await` in `restart`'s cancel-and-settle.
- Do NOT import bus, scheduler, telemetry, or HA modules here — the guard must be standalone (this is what lets #1027 reuse it). Counters are plain ints; persistence/exposure is entirely T02/T03's concern.
- `python.md` rules: no `from __future__ import annotations`, `X | None` not `Optional`, all imports top-of-file.

## Verify
- [ ] FR#1: `ExecutionMode` StrEnum exists in `types/enums.py` with exactly `single`/`restart`/`queued`/`parallel` and is exported alongside the other enums.
- [ ] FR#4: unit test shows a `single` guard drops the second trigger while the first runs (exactly one run).
- [ ] FR#5: the `single` drop increments `suppressed` and emits a DEBUG log (asserted via the counter, not log capture).
- [ ] FR#6: unit test shows a `restart` guard cancels the running invocation and starts the new one.
- [ ] FR#7: the cancelled invocation observes `CancelledError` and no exception escapes the guard.
- [ ] FR#8: unit test shows a `queued` guard runs N triggers in arrival order, one at a time.
- [ ] FR#9: a `queued` guard at cap drops the newest trigger and preserves the existing queue.
- [ ] FR#10: the `queued` cap drop increments `dropped` and emits a DEBUG log.
- [ ] FR#11: unit test shows a `parallel` guard runs M triggers concurrently (pass-through).
- [ ] FR#13: a `restart` A→B→C sequence never has two running invocations concurrently (the running counter never exceeds 1).
- [ ] FR#15: the guard exposes live `suppressed`/`dropped` integer counts.
- [ ] FR#17: `release()` cancels the tracked task, clears the deque, and pending factories do not run.
- [ ] AC#5: test asserts no two concurrent running invocations across rapid `restart` A→B→C.
- [ ] AC#12: test asserts `release()` on a `queued` guard with pending items retains no reference and runs none of them.
