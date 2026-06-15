---
task_id: "T02"
title: "Move reschedule to dispatch time and route invocations through the guard"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#5", "FR#13", "FR#14", "FR#16", "FR#17", "FR#18", "AC#1", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#12", "AC#14", "AC#15", "AC#16"]
---

## Summary

The core, highest-risk change. Restructure `SchedulerService.dispatch_and_log` so recurring jobs
reschedule the next occurrence at dispatch time (before the run), the current due fire always runs,
and the invocation routes through the job's `ExecutionModeGuard`. Add the in-lock `_dequeued`
re-check, the stall watchdog, and guard release on cancel/removal. This is what makes overlap modes
observable. Behavior is preserved for jobs that complete within their interval.

## Prompt

Implement design.md "Architecture §1 (Dispatch-time reschedule)" and "§3 (Routing invocations
through the guard)", honoring the Edge Cases and the "Guard wiring with a completion bridge" and
"Stall watchdog" Convention Examples in context.md.

1. **Restructure `dispatch_and_log` (`src/hassette/core/scheduler_service.py:278`)** to the Option B
   ordering: skip-if-dequeued → compute next → (enqueue next OR mark for removal) → run-through-guard
   → remove-if-marked.
   - The current due fire ALWAYS runs once popped (FR#16). Compute the next occurrence first (reuse
     the `reschedule_job` next-run computation at `scheduler_service.py:350`). If it returns a future
     time, enqueue one heap copy BEFORE invoking. If it returns `None` or the trigger raises, enqueue
     nothing and remove the job AFTER the current fire completes (never skip the current fire).
   - One-shots (`next_run_time()` → `None`): run once, remove after — unchanged observable behavior.

2. **In-lock `_dequeued` re-check (FR#17).** `dequeue_job` (`scheduler_service.py:435`) is lockless
   and sets `job._dequeued = True` (line 458) at any await point. Add a second `if job._dequeued:
   return`/skip check held INSIDE the queue lock in the enqueue path (in `_ScheduledJobQueue.add` or
   a guarded wrapper), immediately before `_queue.push`, atomic with the push. The entry-level check
   at line 284 stays. Push-then-check is insufficient.

3. **Guard routing (`run_with_guard` equivalent, mirror `HandlerInvoker.run_with_mode`).** Replace
   the direct `await self.run_job(job)` with mode-aware routing:
   - `parallel`: `await self.run_job(job)` inline (concurrency comes from `serve()` spawning one
     dispatch task per due-pop — do NOT route parallel through `guard.run`'s tracked path).
   - `single`/`restart`/`queued`: build a `run_and_track` callable that spawns the invocation via
     `self.task_bucket.spawn(...)` wrapped in the stall watchdog (below) and returns the task; call
     `await job.guard.run(run_and_track)`; bridge completion with a per-invocation future resolved
     when the spawned task settles (immediately for `SUPPRESSED`/`DROPPED`). Swallow the
     `CancelledError` a `restart` cancel surfaces so the dispatch task doesn't crash.

4. **Stall watchdog (FR#18).** Wrap the spawned `run_job` in a stall watch mirroring
   `invocation_with_stall_watch`/`warn_stalled` (`bus/listeners.py:314-329`): a
   `loop.call_later(STALL_THRESHOLD_SECONDS, ...)` that logs a WARNING naming the job and mode if the
   invocation is still running at the threshold, cancelled in `finally`. REUSE the shared
   `STALL_THRESHOLD_SECONDS` constant (`bus/listeners.py:27`) — import it, do not redefine. Parallel
   gets no stall watch.

5. **Guard release on cancel/removal (FR#14).** Where a job is cancelled or removed (`dequeue_job`,
   `_remove_job`, `_remove_jobs_by_owner`), call `await job.guard.release()` (or schedule it) so the
   in-flight invocation is cancelled and queued factories are dropped. Note in a comment the inherited
   `drain_next`/`release` interleave edge (FR#14) — do NOT modify the guard to fix it.

6. **`trigger_due_jobs` (`scheduler_service.py:396`):** must NOT block on the completion bridge for
   `QUEUED_ACCEPTED` outcomes (deadlocks under a frozen clock — see Edge Cases). Ensure the harness
   path lets queued multi-tick tests advance via `await asyncio.sleep(0)` + a guard-drain helper.

7. **Tests (same task).** Adapt affected existing tests and add new coverage per design.md Test
   Strategy. New: dispatch-time reschedule timing (overrun enqueues next before run completes);
   per-mode overlap (single suppresses, queued serializes + cap, restart cancels+records, parallel
   concurrent); current-fire-runs-on-trigger-error (FR#16); dequeued race (FR#17); stall watchdog
   (FR#18, threshold patched low, asserted via the watchdog firing path NOT log capture); guard
   release on cancel (FR#14). Adapt `tests/integration/test_scheduler.py`,
   `tests/unit/core/test_scheduler_service_dequeue.py`, `tests/integration/test_app_harness_simulation.py`.

Do NOT change the public scheduling API (T01), persistence (T03), or the state-proxy caller (T04).

## Focus

- `dispatch_and_log` today (`scheduler_service.py:278-305`): runs `run_job` then `reschedule_job`.
  `reschedule_job` (line 350) computes `next_run_time`, handles trigger-raise/`None` via
  `_remove_job`, handles non-future delta (advance 1s), and `enqueue_job`s. You are reordering and
  splitting this, not rewriting the next-run math.
- `enqueue_job` (line 106) calls `apply_jitter_to_heap` then `_job_queue.add` (line 494, holds
  `FairAsyncRLock`). The in-lock `_dequeued` check belongs at the push site inside that lock.
- `serve()` (line 84) spawns `dispatch_and_log` per due job via `task_bucket.spawn` — this is why
  parallel concurrency works without routing parallel through the guard.
- Reference for the exact bridge + stall structure: `HandlerInvoker.run_with_mode`
  (`bus/listeners.py:272-329`), including `pending_done` future handling and
  `invocation_with_stall_watch`. The scheduler's analogue lives on `SchedulerService` (or a small
  helper), keyed off `job.guard`/`job.mode`.
- `ExecutionModeGuard.run` (`execution_mode.py:63`) returns an `Outcome`; `queued` is strictly
  serial (one live task; `drain_next` chains the next on done-callback) — do not assume concurrency.
- `restart`-cancelled execution row: `CommandExecutor.execute` already enqueues a `cancelled`
  record on `CancelledError` before re-raising (`command_executor.py:270-272`) — delivery is
  best-effort (FR#13), do not add a guaranteed path.
- Single heap-copy invariant: a job is popped before dispatch and re-enqueued exactly once — never
  push a second copy. The reschedule-then-run ordering must preserve this.
- `tests/integration/test_scheduler.py` is 521 lines — read it before changing; some tests assume
  the post-completion reschedule timing and will need updating (jobs completing within interval must
  still produce identical fire sequences — FR#3/AC#3).

## Verify

- [ ] FR#1: an overrunning recurring job has its next occurrence on the heap before the current invocation completes.
- [ ] FR#2: one-shots fire once and are removed; timing unchanged.
- [ ] FR#3: a job completing within its interval produces an identical fire-time sequence to today.
- [ ] FR#5: each mode's overlap behavior is applied via the per-job guard (suppress/serialize/restart/concurrent).
- [ ] FR#13: a restart-cancelled invocation is recorded `cancelled` when the write queue has capacity.
- [ ] FR#14: cancel/removal calls `guard.release()`, cancelling the in-flight invocation and dropping queued factories.
- [ ] FR#16: a trigger that raises/returns None still runs the current due fire, then removes the job (no future fires).
- [ ] FR#17: a `_dequeued` re-check is held inside the queue lock atomic with the re-enqueue push; a job cancelled mid-dispatch is not re-pushed.
- [ ] FR#18: a non-parallel invocation still running past STALL_THRESHOLD_SECONDS logs a WARNING naming the job and mode; parallel does not.
- [ ] AC#1: next occurrence is enqueued before the current run completes (overrun, gated by an event).
- [ ] AC#3: with/without this change, a within-interval recurring job has the same fire sequence.
- [ ] AC#4: `single` overrun suppresses re-fires; `guard.suppressed` increments.
- [ ] AC#5: `queued` overrun runs every tick in order one at a time until the cap, then drops newest; `guard.dropped` increments.
- [ ] AC#6: `restart` re-fire cancels the in-flight run (recorded `cancelled` when capacity allows) and starts fresh.
- [ ] AC#7: `parallel` overrun runs invocations concurrently.
- [ ] AC#12: cancelling a job with an in-flight/queued invocation cancels and clears it.
- [ ] AC#14: a recurring job whose trigger raises still runs the current fire, then is removed.
- [ ] AC#15: a job cancelled between dispatch entry and re-enqueue is not pushed back; no later spurious dispatch.
- [ ] AC#16: a single/restart/queued invocation past the stall threshold emits a WARNING; a parallel one does not.
