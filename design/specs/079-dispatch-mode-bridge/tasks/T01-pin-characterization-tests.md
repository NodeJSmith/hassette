---
task_id: "T01"
title: "Pin bus stall-watch and release-drain behavior"
status: "done"
depends_on: []
implements: ["AC#3"]
---

## Summary

Add the missing bus-side characterization tests that pin current behavior before
any extraction. The scheduler already has a stall-watch test; the bus has none, and
the bus `release_guard` → `pending_done` drain is only covered indirectly. These
pins pass against the **current** code and become the safety net that proves the
later extraction is behavior-preserving. This is the RED-first step of the
verifiable commit sequence — do not change any `src/` code in this task.

## Target Files

- modify: `tests/integration/bus/test_execution_modes.py`
- read: `src/hassette/bus/listeners.py`
- read: `tests/integration/test_scheduler_mode.py`
- read: `design/specs/079-dispatch-mode-bridge/tasks/context.md`

## Prompt

Add two integration tests to `tests/integration/bus/test_execution_modes.py`,
mirroring the conventions in `tests/integration/test_scheduler_mode.py`.

1. **Bus stall-watch characterization test.** Mirror
   `test_stall_watchdog_emits_warning_for_non_parallel`
   (`tests/integration/test_scheduler_mode.py:960`). Register a non-parallel
   (`mode="single"`, `timeout_disabled=True`) listener whose handler sets an
   `asyncio.Event` `started` then awaits a `gate` event. **Patch target setup
   (load-bearing — get this wrong and the watchdog never fires, giving a
   false-green pin):** `test_execution_modes.py` does not currently import the
   `bus.listeners` module object. Add `import hassette.bus.listeners as
   bus_listeners_module` (mirroring `tests/integration/test_scheduler_mode.py:31`'s
   `import hassette.core.scheduler_service as scheduler_service_module`). Then patch
   `bus_listeners_module.STALL_THRESHOLD_SECONDS` to `0.05` and spy on the class
   method via `unittest.mock.patch.object(bus_listeners_module.HandlerInvoker,
   "warn_stalled")`. Dispatch an event that matches the
   listener, wait for `started`, then `await asyncio.sleep(0.2)` (longer than the
   patched threshold). Assert the dispatch is still pending and that `warn_stalled`
   fired. **Against the current code, assert `mock_warn.assert_called_once_with()`
   (no arguments)** — `warn_stalled` currently takes no threshold parameter. T03
   will update this assertion when the signature changes. Unblock the gate and
   await clean shutdown.

2. **Bus release-drain test.** Add an explicit assertion (or a focused new test
   alongside `test_cancelling_queued_listener_releases_pending` at
   `test_execution_modes.py:366`) that a `QUEUED_ACCEPTED` trigger's `pending_done`
   future is resolved when the listener is cancelled/released before the queued
   factory ever runs — i.e. the outer dispatch task unwinds rather than hanging.

Use the deterministic gate pattern (`asyncio.Event`, `wait_for(started.wait())`) —
never `await asyncio.sleep(0)` to reach the blocked state (see context.md).

Run the new tests and confirm they pass against the current (unmodified) code.

## Focus

- The bus stall watchdog lives in `HandlerInvoker.invocation_with_stall_watch`
  (`bus/listeners.py:339`); it calls `self.warn_stalled` (`:347`) via
  `call_later(STALL_THRESHOLD_SECONDS, self.warn_stalled)`. `STALL_THRESHOLD_SECONDS`
  is at `bus/listeners.py:27`.
- The bus path reaches dispatch differently from the scheduler — there is no
  `dispatch_and_log(job)` equivalent; events flow through the bus fan-out. Study how
  the existing `test_execution_modes.py` tests trigger a listener (likely via firing
  an event through the harness/bus) and follow that pattern rather than copying the
  scheduler's `create_task(dispatch_and_log(...))` shape literally.
- `warn_stalled` (`bus/listeners.py:347`) builds its message from
  `handler_short_name` + `mode`. Spying on the method (not asserting log text) is the
  robust check — a deleted `call_later` registration would pass a weaker
  "is-still-running" check but fail the spy assertion.
- This task must be committed before T03 (the bus migration) — it is the pin that
  gates that change.

## Verify

- [ ] AC#3: A bus stall-watch characterization test exists in
      `tests/integration/bus/test_execution_modes.py`, spies on
      `HandlerInvoker.warn_stalled`, and passes against the current code — asserting
      the watchdog fires after the patched 0.05s threshold via
      `mock_warn.assert_called_once_with()` (no arguments, current signature; T03
      updates this to the threshold argument). An explicit bus release-drain
      assertion also exists and passes.
