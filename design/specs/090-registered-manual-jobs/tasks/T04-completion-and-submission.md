---
task_id: "T04"
title: "Implement completion retention and manual submission"
status: "planned"
depends_on: ["T03"]
implements: ["FR#9", "FR#11", "FR#12", "FR#13", "FR#15", "FR#17", "FR#24", "FR#25", "AC#3", "AC#4"]
---

## Summary

Implement the completion state transition in `dispatch_and_log()` (three-way branch: scheduled/completed/waiting), the `submit_job()` service method for fire-and-observe manual submission, and the `trigger_error` completion path. Completed one-shots remain live and submit-capable. Manual submission bypasses predicates and never mutates automatic schedule state.

## Target Files

- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/scheduler/classes.py`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > Completion, Manual Submission)
- modify: `tests/unit/core/test_scheduler_service_dequeue.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`
- modify: `tests/integration/test_scheduler.py`
- modify: `tests/integration/test_scheduler_mode.py`

## Prompt

**Implement the three-way dispatch branch** in `SchedulerService.dispatch_and_log()`:

Currently `dispatch_and_log()` has a binary branch on `next_run_time()`: concrete time → enqueue, `None` → remove. Replace with:

1. Concrete `ZonedDateTime` → `job.transition_to(SCHEDULED, next_run=..., fire_at=...)` and enqueue.
2. `None` → `job.transition_to(COMPLETED)` and do NOT enqueue. The job remains in the live registry.
3. `WAITING` sentinel (EntityTime only) → `job.transition_to(WAITING)`, do NOT enqueue, do NOT mark completed, keep watcher active.
4. Trigger calculation raises → log the exception, let the current due occurrence proceed with dispatch-local timing, then `job.transition_to(COMPLETED, reason=ScheduleStatusReason.TRIGGER_ERROR)`.

**Dispatch-local timing:** When the final occurrence is popped, copy `next_run`/`fire_at` into local variables before calling `transition_to(COMPLETED)` on the job. Predicate evaluation, lag calculation, and execution use these local copies.

**Persist status transitions:** After each `transition_to()` call, persist the new `schedule_status` and `schedule_status_reason` to the database through the existing command/repository boundary.

**Implement `submit_job()`** on `SchedulerService`:
1. Confirm `job.db_id` maps to the same object in `_jobs_by_id`; otherwise raise `JobRemovedError`.
2. Spawn `run_job_with_guard(job, trigger_mode="manual")` through `SchedulerService.task_bucket`.
3. Return `None` immediately.

No inspection of schedule status, timing, trigger, or predicate. No preflight `single` mode or queue capacity check. Existing guard behavior decides outcomes.

**Wire `Job.submit()`** to call `self._scheduler_service.submit_job(self)`.

**Manual submission invariants:**
- Uses the job's registered args/kwargs.
- Bypasses the job's predicate.
- Does NOT consume, move, or complete a pending automatic occurrence.
- `run_job()` must avoid schedule-lag calculations for manual execution — calculate lag only for automatic dispatches with concrete `fire_at`.

**Update existing tests:**
- Tests asserting completed one-shots are removed → assert they remain live and submit-capable.
- Tests asserting `NO_OCCURRENCE` at dispatch time → assert `WAITING` transition.
- Add tests for `submit_job()` across all execution modes (single/queued/restart/parallel).
- Add tests for predicate bypass on manual submission.
- Add tests for removed-handle `JobRemovedError`.
- Add tests for manual submission not consuming a pending one-shot.
- Add tests for `trigger_error` completion.

See design doc: Architecture > Completion, Manual Submission.

## Focus

- `dispatch_and_log()` currently calls `self.remove_job(job)` for exhausted triggers — this must change to a completion transition that keeps the job live.
- The `run_job()` method computes schedule lag from `fire_at` — manual trigger telemetry should skip this or set lag to `None`/0.
- `trigger_mode="manual"` is already recorded in execution telemetry — verify this still works.
- `ExecutionModeGuard` is per-`Job` and reused unchanged — `submit_job()` intentionally does not check the guard before spawning. The guard handles suppression/queuing.
- The pending one-shot edge case: if a one-shot has `next_run` set and someone submits manually, the automatic occurrence must still fire at its scheduled time. `submit_job()` must not call `transition_to()`.

## Verify

- [ ] FR#9: A job whose final automatic occurrence is consumed transitions to `COMPLETED` and remains in the live registry.
- [ ] FR#11: `Job.submit()` returns `None` without accepting per-invocation arguments.
- [ ] FR#12: Manual submission uses registered args/kwargs, bypasses predicate, and records `trigger_mode="manual"` telemetry.
- [ ] FR#13: Manual submission preserves existing execution-mode behavior. Suppression/drop outcomes are not synchronously returned.
- [ ] FR#15: A live job always accepts submission (no preflight rejection).
- [ ] FR#17: Manual submission does not consume, move, or complete a pending automatic occurrence.
- [ ] FR#24: Ordinary trigger completion (`next_run_time() → None`) still works. Existing first-occurrence and `if_past` behavior unchanged.
- [ ] FR#25: Trigger calculation failure produces `COMPLETED` with `schedule_status_reason=TRIGGER_ERROR`.
- [ ] AC#3: Tests demonstrate one-shots become completed but remain submit-capable. Manual submission does not consume pending occurrences.
- [ ] AC#4: Tests demonstrate `submit()` behavior for all execution modes, fixed arguments, predicate bypass, manual telemetry, and removed-handle errors.
