---
task_id: "T02"
title: "Enforce DROP_NEWEST at the dispatch acquire gate with a bp_dropped counter"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "AC#1", "AC#2", "AC#3"]
---

## Summary
Add the dispatch-loop enforcement: when the global dispatch semaphore is saturated, a `DROP_NEWEST`
listener skips the event (no acquire, no spawn) and increments a `bp_dropped` counter; `BLOCK` and an
omitted policy take the existing acquire-then-spawn path unchanged. The counter lives on
`HandlerInvoker` (not the overlap guard). Also fix the saturation warning text so it no longer asserts
"waiting for a slot" now that listeners may drop. Unit tests pin drop, block, and no-leak behavior.

## Target Files
- modify: `src/hassette/core/bus_service.py`
- modify: `src/hassette/bus/listeners.py`
- modify: `tests/unit/core/test_bus_dispatch_semaphore.py`
- read: `design/specs/076-listener-backpressure-policy/design.md`
- read: `design/specs/076-listener-backpressure-policy/tasks/context.md`

## Prompt
Implement enforcement per the design doc's `## Architecture` §4 and §5 (counter placement only) and the
warning-text Edge Case.

1. **`HandlerInvoker.bp_dropped`** (`src/hassette/bus/listeners.py:137`): add `bp_dropped: int` to the
   `HandlerInvoker` dataclass (`@dataclass(slots=True)` — add it to the slots/fields, initialized to 0).
   Do NOT add it to `ExecutionModeGuard` in `src/hassette/execution_mode.py` — keeping the overlap guard
   pure and excluding scheduler jobs is the whole point (design §5, context Key Decision 4).

2. **Acquire-gate branch** (`src/hassette/core/bus_service.py`, the per-listener loop at ~384-406):
   inside the existing `if self._dispatch_semaphore.locked():` block (which already calls
   `warn_dispatch_saturated()`), branch before the acquire:
   ```python
   if self._dispatch_semaphore.locked():
       self.warn_dispatch_saturated()
       if listener.options.backpressure is BackpressurePolicy.DROP_NEWEST:
           listener.invoker.bp_dropped += 1   # single writer: this loop, on the loop, no await
           self.logger.debug("backpressure drop_newest: skipping event for %s", listener.identity.name)
           continue  # no acquire, no spawn, no pending/idle bookkeeping
   await self._dispatch_semaphore.acquire()
   # ... unchanged BLOCK path below ...
   ```
   Add an inline comment recording the single-writer / no-await invariant (design Key Constraints).
   The `continue` MUST come before any `_dispatch_pending += 1` / `_dispatch_idle_event.clear()`.

3. **Warning text** (`src/hassette/core/bus_service.py:151-155`): reword `warn_dispatch_saturated`'s
   message so it does not assert dispatches are "waiting for a slot" — make it policy-neutral (the bus
   is saturated; listeners may wait or drop per their policy). Keep the existing rate limiting.

4. **Tests** (`tests/unit/core/test_bus_dispatch_semaphore.py`): mirror the existing saturation harness.
   Add: a `DROP_NEWEST` listener under a held-locked semaphore is skipped (handler not invoked) and its
   `bp_dropped` increments by exactly one per dropped event; a `DROP_NEWEST` listener under the limit
   dispatches normally; a `BLOCK` listener still blocks-then-runs under saturation; the five existing
   tests (lines 38, 84, 104, 120, 152) still pass unchanged; a dropped event does not perturb
   `_dispatch_pending`/idle (no `await_dispatch_idle` hang).

## Focus
- The acquire gate is `bus_service.py:384-406`. The `locked()`→branch→`acquire()` sequence has NO
  `await` between `locked()` and the decision — this is what makes both the saturation check and the
  `bp_dropped += 1` race-free. Do not insert an await there.
- `release_dispatch_slot` is an asyncio done-callback (`bus_service.py:137-143`); it runs via
  `call_soon` and does not preempt the synchronous gate — the existing reasoning holds for the new
  branch too.
- Import `BackpressurePolicy` from `hassette.types.enums` (top of file, no lazy import).
- `bp_dropped` is read in T04 by `live_execution_counts` via `listener.invoker.bp_dropped` — this task
  only creates and increments it.
- This task and T03 both modify `bus_service.py`; T03 depends on this task to serialize those edits.

## Verify
- [ ] FR#3: A `BLOCK` (or omitted-policy) listener acquires-then-spawns exactly as before; the five
  existing semaphore tests pass unchanged.
- [ ] FR#4: Under a held-locked semaphore, a `DROP_NEWEST` listener's handler is not invoked and
  `listener.invoker.bp_dropped` increments by one per dropped event.
- [ ] FR#5: Under the limit (not saturated), a `DROP_NEWEST` listener dispatches normally.
- [ ] FR#6: `HandlerInvoker.bp_dropped` exists, initializes to 0, and is incremented only at the gate.
- [ ] AC#1: `test_dispatch_under_limit_runs_all_without_blocking` and the other existing tests pass; a
  `DROP_NEWEST` listener under the limit runs every event.
- [ ] AC#2: New test: held-locked semaphore → `DROP_NEWEST` skipped, handler not called, counter +1/drop.
- [ ] AC#3: New test: held-locked semaphore → `BLOCK` listener blocks until a slot frees, then runs.
