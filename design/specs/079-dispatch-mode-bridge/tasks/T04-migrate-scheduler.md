---
task_id: "T04"
title: "Migrate the scheduler call site to the shared helpers"
status: "done"
depends_on: ["T02"]
implements: ["FR#8", "FR#9", "AC#2"]
---

## Summary

Rewrite the scheduler dispatch glue (`SchedulerService` / `ScheduledJob` path) to
call the shared helpers, add the new `execution_mode` import, repoint the three drain
call sites, delete the scheduler-local duplicated code, and change `warn_stalled_job`
to take the threshold. Adapt the one scheduler stall-watch test assertion. This is a
behavior-preserving migration of the scheduler half.

## Target Files

- modify: `src/hassette/core/scheduler_service.py`
- modify: `tests/integration/test_scheduler_mode.py`
- read: `src/hassette/execution_mode.py`
- read: `src/hassette/scheduler/classes.py`
- read: `tests/unit/core/test_scheduler_service_dequeue.py`
- read: `tests/unit/core/test_scheduler_service_reschedule.py`
- read: `design/specs/079-dispatch-mode-bridge/design.md`
- read: `design/specs/079-dispatch-mode-bridge/tasks/context.md`

## Prompt

In `src/hassette/core/scheduler_service.py`:

1. Add a NEW top-level import (the module imports nothing from `execution_mode`
   today): `from hassette.execution_mode import STALL_THRESHOLD_SECONDS, drain_pending_done, run_through_guard, run_with_stall_watch`.
   Remove the local `STALL_THRESHOLD_SECONDS = 60.0` definition (`:32`).
2. Rewrite `run_job_with_guard` (`:384`) to keep the parallel fast-path
   (`await self.run_job(job)` inline) then `await run_through_guard(guard=job.guard, spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name), pending_done=job.pending_done, invoke=lambda: self.run_job(job), warn=lambda secs: self.warn_stalled_job(job, secs), spawn_name="scheduler:mode_invocation", threshold=STALL_THRESHOLD_SECONDS)`.
   Keep the method named `run_job_with_guard` with its `(job)` signature unchanged —
   only the body changes.
3. Delete the local `invocation_with_stall_watch` method (`:433`) and the standalone
   `drain_pending_done` method (`:595`).
4. Replace the three `self.drain_pending_done(job)` call sites
   (`_remove_jobs_by_owner` `:132`, `_remove_job` `:217`, `dequeue_job`'s
   `_release_and_drain` `:589`) with `drain_pending_done(job.pending_done)` using the
   imported free function.
5. Change `warn_stalled_job` (`:448`) signature to
   `warn_stalled_job(self, job, threshold: float)` and log the passed `threshold`
   instead of the module constant. Keep the message shape (job name + mode + duration).
6. Move the `drain_next`/`release` interleave caveat comment
   (`scheduler_service.py:584-586`) out — it now lives in the shared
   `run_through_guard`/`drain_pending_done` docstring (added in T02). Leave a one-line
   pointer to issue #1099 if helpful, but remove the duplicated explanation.
7. Remove stale cross-reference comments pointing at the bus by line number.

In `tests/integration/test_scheduler_mode.py`: update
`test_stall_watchdog_emits_warning_for_non_parallel` (`:999`) assertion from
`mock_warn.assert_called_once_with(job)` to `mock_warn.assert_called_once_with(job, 0.05)`
(the lambda `warn=lambda secs: self.warn_stalled_job(job, secs)` now passes the
threshold). Confirm `test_parallel_mode_has_no_stall_watchdog` (`:1006`) still passes
unchanged (parallel never arms the watchdog).

Run `tests/integration/test_scheduler_mode.py`,
`tests/unit/core/test_scheduler_service_dequeue.py`, and
`tests/unit/core/test_scheduler_service_reschedule.py`; confirm all pass.

## Focus

- `run_job_with_guard` stays a method with the same `(job)` signature — only its body
  changes. This matters: `tests/unit/core/test_scheduler_service_dequeue.py` and
  `tests/unit/core/test_scheduler_service_reschedule.py` spy/mock
  `svc.run_job_with_guard` (gap-check finding — not in the design's original Impact
  list). They should pass untouched, but you MUST run them to confirm the
  name/signature was preserved.
- `pending_done` lives on `ScheduledJob` (`scheduler/classes.py:245`); its docstring
  references the bus by line number — update or drop that stale cross-ref while here.
- The scheduler parallel path stays `await self.run_job(job)` inline (FR#9).
- `dequeue_job` is sync and spawns `_release_and_drain` detached (`:587-591`); keep
  that structure — only the drain call inside it changes to the imported function.
- The patch target `scheduler_service_module.STALL_THRESHOLD_SECONDS` stays valid
  because the call site reads the module-local imported name at call time; the test
  assertion change is the only test edit needed for the stall test.
- Do not touch `bus/listeners.py` in this task.

## Verify

- [ ] FR#8: `run_job_with_guard` calls `run_through_guard`; all three drain sites call
      the imported `drain_pending_done(job.pending_done)`; the local
      `invocation_with_stall_watch` and `drain_pending_done` methods and the local
      `STALL_THRESHOLD_SECONDS` are removed; the new `execution_mode` import is present.
- [ ] FR#9: the scheduler parallel path remains an inline `await self.run_job(job)`.
- [ ] AC#2: `tests/integration/test_scheduler_mode.py` passes with the adapted
      `assert_called_once_with(job, 0.05)` assertion; the dequeue and reschedule unit
      tests pass unchanged.
