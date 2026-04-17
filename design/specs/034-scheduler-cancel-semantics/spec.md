---
feature_number: "034"
feature_slug: "scheduler-cancel-semantics"
status: "approved"
created: "2026-04-17T09:30:00-05:00"
---

# Spec: Clarify Cancel vs Remove Job Semantics in Scheduler

## Problem Statement

The Scheduler exposes two overlapping mechanisms for stopping a scheduled job: a public `remove_job()` method and a public `cancel_job()` method. Both are visible to framework users, but they have subtly different semantics — `cancel_job` persists a cancellation timestamp to the database for telemetry, while `remove_job` silently dequeues without any durable record.

Additionally, `ScheduledJob.cancel()` — the documented primary cancellation method — only sets a transient `cancelled` flag. It does not dequeue the job or write to the database; it relies on dispatch-path guard clauses to prevent execution. This means the user-facing API (`job.cancel()`) performs an incomplete cancellation, while the full cancellation (`Scheduler.cancel_job()`) is less discoverable.

This ambiguity makes it unclear which method a user should call, whether the `cancelled` flag has runtime significance beyond the guards, and what the intended lifecycle of a stopped job is.

## Goals

- Make `job.cancel()` perform a complete cancellation (dequeue + DB persist) by delegating to `Scheduler.cancel_job()` via a back-reference.
- Establish `cancel_job` and `cancel_group` as the sole public Scheduler methods for stopping jobs, with `job.cancel()` as the primary user-facing entry point.
- Make internal dequeuing invisible to users by converting `remove_job` and `remove_all_jobs` to private methods.
- Make `_dequeue_job` perform a synchronous inline heap removal so that the dispatch-path guards and transient `cancelled` flag become genuinely dead code.
- Simplify telemetry enrichment to rely solely on the durable database `cancelled_at` column.
- Update all user-facing documentation to reflect the simplified surface.

## User Scenarios

### Framework developer: Automation author

- **Goal:** Stop a scheduled job that is no longer needed.
- **Context:** Writing an app that schedules periodic tasks and needs to cancel some based on runtime conditions.

> A developer calls `job.cancel()` on a job reference, or `self.scheduler.cancel_group("my_group")` for bulk cancellation. The cancellation is persisted to the database and the job is removed from the scheduling heap. `job.cancel()` delegates to the scheduler internally — the developer does not need to hold a scheduler reference to cancel a single job.

## Functional Requirements

1. `ScheduledJob` must hold a back-reference to its owning `Scheduler` resource, declared as `_scheduler: "Scheduler | None" = field(default=None, repr=False, compare=False)` and set post-construction in `schedule()`. `ScheduledJob.cancel()` must delegate to `Scheduler.cancel_job(self)`, performing a full cancellation (DB persist + dequeue). If `_scheduler` is None (bare test construction), `cancel()` must raise `RuntimeError` with a clear message. `cancel_job` must NOT call `job.cancel()` internally — it is the implementation target, not the caller.
2. The public method `remove_job` on the `Scheduler` resource must be renamed to a private method `_dequeue_job`. It must perform a synchronous inline heap removal (directly calling `_queue.remove_item()` rather than spawning an async task) so that the job is immediately absent from the heap when `cancel_job` returns.
3. The public method `remove_all_jobs` on the `Scheduler` resource must be renamed to `_remove_all_jobs` (return type unchanged: `asyncio.Task`). Callers: `on_shutdown`, `test_utils/reset.py`, `test_scheduler_resource.py`, `test_scheduler_job_names.py`. Test files may call the underscore-prefixed method directly — this is consistent with existing patterns (e.g., `hassette._bus_service`).
4. `cancel_job` must: remove the job from `_jobs_by_name` and `_jobs_by_group`, spawn the DB write (`mark_job_cancelled`) when `db_id` is set, and call `_dequeue_job`. It must NOT call `job.cancel()`.
5. `cancel_group` must delegate to `cancel_job` per-member rather than inlining the cancel+persist+remove sequence. After delegation, it clears the group entry from `_jobs_by_group`.
6. `cancel_job` and `cancel_group` remain as public methods on the `Scheduler` resource. `job.cancel()` is the primary user-facing entry point for single-job cancellation.
7. The `cancelled` boolean flag on `ScheduledJob` must be removed. No in-memory transient cancellation state should exist. The `cancel()` method on `ScheduledJob` is retained but repurposed as delegation to the scheduler.
8. The dispatch-path guard clauses that check `job.cancelled` in `run_job` and `reschedule_job` must be removed. The guard in `_dispatch_and_log` must be replaced with a `job._dequeued` check to protect against the race where the serve loop pops a job before `cancel_job` runs.
9. Telemetry enrichment must rely solely on the database `cancelled_at` column. The `live_job.cancelled or js.cancelled` OR expression must be simplified to use only `js.cancelled`. Telemetry may briefly show a job as active between `cancel_job` being called and `cancelled_at` being committed to the DB; this is accepted behavior.
10. All internal callers that previously used the public `remove_job` or `remove_all_jobs` must be updated to use the renamed private methods. Specifically: `state_proxy.py` (lines 87 and 291) must use `_dequeue_job`, not `cancel_job`, to avoid writing spurious `cancelled_at` records on HA disconnect/reconnect cycles.
11. All user-facing documentation — including the management guide, code snippets, migration guide, and recipe prose — must be updated to remove references to `cancelled` as an inspectable attribute and `remove_job` as a callable method. The management guide must document the `list_jobs()` idiom as the replacement for inspecting cancellation state and the null-reference pattern (`self.my_job = None`) as the guard against double-cancel. Stale code comments (`scheduler.py:192-194` OR-enrichment reference) and docstrings (`classes.py matches()` listing `cancelled`) must be updated. The `scheduler_job_metadata.py` snippet that accesses `job.cancelled` must be updated.
12. Test assertions on `job.cancelled` must be replaced with behavioral equivalents (e.g., the job is absent from `list_jobs()`, a subsequent `trigger_due_jobs()` does not invoke the handler, or the job's `cancelled_at` is non-null in the DB). An integration test must verify that `job.cancel()` via the back-reference path, on a registered job with a non-None `db_id`, results in `cancelled_at IS NOT NULL` in the database.

## Edge Cases

- A job that is cancelled while its handler is mid-execution: the handler runs to completion (existing behavior, unchanged), and `cancel_job` dequeues it synchronously to prevent rescheduling. The job is absent from the heap when `reschedule_job` would look for it.
- Framework-internal callers (shutdown, exhaustion, StateProxy reconnect) that previously called `remove_job`: these use `_dequeue_job` directly. No `cancelled_at` record is written — only user-initiated cancellations via `cancel_job`/`cancel_group`/`job.cancel()` produce DB records.
- The `SchedulerService.remove_job` method remains public (no underscore) per framework convention — service-layer methods are public because framework components call them. The underscore convention applies only to the user-facing `Scheduler` resource.
- `ScheduledJob` constructed without a scheduler back-reference (bare test construction, codegen stubs): `cancel()` raises `RuntimeError` with a clear message rather than `AttributeError`.

## Dependencies and Assumptions

- The database `cancelled_at` column already exists and is populated by `cancel_job`. No schema migration is needed.
- `_dequeue_job` performs a synchronous inline heap removal. The dispatch loop cannot encounter a cancelled job because the job is removed from the heap before `cancel_job` returns — no async task spawning, no race window.

## Acceptance Criteria

1. `remove_job` and `remove_all_jobs` are not accessible as public methods on the `Scheduler` resource.
2. `ScheduledJob` has no `cancelled` attribute.
3. `ScheduledJob.cancel()` performs a full cancellation (dequeue + DB persist) via delegation to the owning `Scheduler`.
4. No code in the codebase references `job.cancelled` (the transient flag).
5. After any cancellation path (`cancel_job`, `cancel_group`, `job.cancel()`): the job is absent from `list_jobs()` and a subsequent `trigger_due_jobs()` does not invoke its handler. Cancelling a job before `db_id` is set does not raise an exception and no DB write is attempted.
6. Calling `cancel_job(job)`, `cancel_group(group)`, or `job.cancel()` on a job with a non-None `db_id` results in `cancelled_at IS NOT NULL` in the database for that job.
7. The telemetry enrichment endpoint returns correct `cancelled` status using only DB-derived `cancelled_at`.
8. All user-facing documentation shows `job.cancel()`/`cancel_group` as the job-stopping API with no mention of `remove_job` or `job.cancelled` as an inspectable attribute.
9. Cancelling a group via `cancel_group` invokes `cancel_job` per member (verified by test).
10. All existing tests pass after the rename and flag removal.

## Open Questions

None at this time.
