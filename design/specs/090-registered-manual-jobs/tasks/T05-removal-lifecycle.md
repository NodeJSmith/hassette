---
task_id: "T05"
title: "Implement unified removal and lifecycle cleanup"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#19", "AC#5"]
---

## Summary

Implement the unified service removal operation used by explicit removal, destructive replacement, and owner shutdown/reload. Wire `Job.remove()` to the service. Verify all existing scheduler tests pass after the full rename and registry migration.

## Target Files

- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `src/hassette/scheduler/classes.py`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > Removal)
- modify: `tests/unit/core/test_scheduler_service_dequeue.py`
- modify: `tests/integration/test_scheduler_mode.py`
- modify: `tests/system/test_scheduler.py`

## Prompt

**Implement one service removal operation** in `SchedulerService`:

The operation is used by explicit removal (`Job.remove()`, `Scheduler.remove_job()`), destructive replacement (`if_exists="replace"`), and owner cleanup (`_remove_all_jobs()`). It must:

1. Remove from `_jobs_by_id` first (identity-checked) so no new submission can be accepted.
2. Mark the job with a private removed flag for stale-handle checks.
3. Remove any heap occurrence.
4. Release the `ExecutionModeGuard` — cancel active async execution, drain queued completion futures.
5. Fire per-owner cleanup callbacks (name/group index cleanup, EntityTime subscription cleanup).
6. Persist `removed_at` when the removal represents a completed live registration.

**Wire `Job.remove()`** to call the service removal operation.

**Wire `Scheduler.remove_job(name)`** and `Scheduler.remove_group(group)` to use the new removal path.

**Handle edge cases from the design:**
- Job is removed while popped, running, or holding queued requests → prevents re-enqueue, releases guard, drains futures, makes handle stale.
- Sync handler is active during removal → cancel the awaiting task but do not claim to terminate the worker thread.
- Stale persisted ID submitted during/after app reload → 409 unless a live job has completed registration.

**Update existing tests:**
- `test_scheduler_service_dequeue.py`: split heap removal tests from registration removal tests.
- `test_scheduler_mode.py`: rename cancellation tests to removal, test completed-job guard behavior.
- `test_scheduler.py` (system): test owner cleanup with all four job statuses (scheduled, completed, waiting, manual).

**Full test suite pass:** After this task, all existing scheduler unit, integration, and system tests must pass with the renamed APIs. Run `prek -a` to verify lint and type checking.

See design doc: Architecture > Removal.

## Focus

- The removal operation must handle the case where the job was never added to the heap (manual, waiting, completed). Don't assume a heap entry exists.
- `ExecutionModeGuard` release: for `single` mode, cancel the active task; for `queued` mode, drain pending futures; for `parallel`, cancel all active tasks. Verify existing guard cleanup logic handles these.
- Owner cleanup (`_remove_all_jobs`) now passes the job list from `Scheduler`, not from the heap — manual/waiting/completed jobs are included.
- `register_removal_callback` is an existing pattern — verify it's still called during removal for per-app index cleanup.

## Verify

- [ ] FR#19: Removing a job removes its live registration, heap occurrence, group/name indexes, trigger watcher, cancels active execution, drops queued execution, rejects future submission, and retains historical telemetry.
- [ ] AC#5: Tests demonstrate complete removal and destructive replacement cleanup across registry, heap, indexes, watchers, guards, and persisted `removed_at`.
