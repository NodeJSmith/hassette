---
task_id: "T03"
title: "Migrate the bus call site to the shared helpers"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#7", "FR#9", "AC#1"]
---

## Summary

Rewrite the bus dispatch glue (`HandlerInvoker`) to call the shared helpers added in
T02, delete the bus-local duplicated code, and change `warn_stalled` to take the
threshold. The T01 pins must stay green (with the stall-watch assertion updated for
the new signature). This is a behavior-preserving migration of the bus half.

## Target Files

- modify: `src/hassette/bus/listeners.py`
- modify: `tests/integration/bus/test_execution_modes.py`
- read: `src/hassette/execution_mode.py`
- read: `design/specs/079-dispatch-mode-bridge/design.md`
- read: `design/specs/079-dispatch-mode-bridge/tasks/context.md`

## Prompt

In `src/hassette/bus/listeners.py`:

1. Add the new names to the existing `execution_mode` import at `listeners.py:13`:
   `STALL_THRESHOLD_SECONDS`, `drain_pending_done`, `run_through_guard`,
   `run_with_stall_watch` (alongside `ExecutionModeGuard`). Remove the local
   `STALL_THRESHOLD_SECONDS = 60.0` definition (`:27`).
2. Rewrite `HandlerInvoker.run_with_mode` (`:297`) to: keep the parallel fast-path
   (`if self.mode is ExecutionMode.PARALLEL: await invoke_fn(); return`), then
   `await run_through_guard(guard=self.guard, spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name), pending_done=self.pending_done, invoke=invoke_fn, warn=self.warn_stalled, spawn_name="bus:mode_invocation", threshold=STALL_THRESHOLD_SECONDS)`.
3. Rewrite `release_guard` (`:361`) to `await self.guard.release()` followed by
   `drain_pending_done(self.pending_done)`.
4. Delete the local `invocation_with_stall_watch` method (`:339`).
5. Change `warn_stalled` (`:347`) signature to `warn_stalled(self, threshold: float)`
   and log the passed `threshold` instead of reading the module constant. Keep the
   message shape (handler name + mode + duration).
6. Remove the now-stale cross-reference comments that pointed at the scheduler by
   line number.

In `tests/integration/bus/test_execution_modes.py`: update the T01 bus stall-watch
test's assertion to the new signature — `mock_warn.assert_called_once_with(0.05)`
(the patched threshold is now passed positionally to `warn_stalled`).

Run `tests/integration/bus/test_execution_modes.py` and
`tests/unit/bus/test_execution_mode_guard.py` and confirm all pass.

## Focus

- `run_with_mode` is on the hot path for every non-parallel bus event — the rewrite
  is mechanical but the blast radius is the whole event-dispatch flow. The T01 pins
  plus the existing 14 execution-mode tests are the guard.
- The bus parallel path stays `await invoke_fn()` inline (FR#9) — do not route
  parallel through `run_through_guard`.
- `warn_stalled` is also referenced by the spy in the T01 test; the assertion update
  in this task must match how the lambda calls it. Since `warn=self.warn_stalled` and
  `run_with_stall_watch` calls `warn(threshold)`, `warn_stalled` is invoked as
  `warn_stalled(0.05)` — assert `assert_called_once_with(0.05)`.
- `pending_done` stays a field on `HandlerInvoker` (`:203`); the helper only mutates
  it via the passed reference.
- Do not touch `scheduler_service.py` in this task.

## Verify

- [ ] FR#7: `HandlerInvoker.run_with_mode` and `release_guard` call the shared
      `run_through_guard` / `drain_pending_done`; the local
      `invocation_with_stall_watch` method and inline bridge/drain bodies and the
      local `STALL_THRESHOLD_SECONDS` are removed.
- [ ] FR#9: the bus parallel path remains an inline `await invoke_fn()`, not routed
      through `run_through_guard`.
- [ ] AC#1: `tests/integration/bus/test_execution_modes.py` and
      `tests/unit/bus/test_execution_mode_guard.py` pass; the T01 stall-watch test
      passes with the updated `assert_called_once_with(0.05)` assertion.
