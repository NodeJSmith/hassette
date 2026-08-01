---
task_id: "T03"
title: "Add live registry and registration paths"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#5", "FR#6", "FR#7", "FR#8", "FR#20", "FR#21", "AC#1", "AC#2"]
---

## Summary

Add `SchedulerService._jobs_by_id` as the service-level live registry. Implement `Scheduler.register()` for manual-only jobs and refactor `Scheduler.schedule()` to share common job construction. Implement the three-step `add_job()` sequence (persist → registry → enqueue). Implement EntityTime waiting state transitions (replacing `NO_OCCURRENCE` with `WAITING` sentinel). Implement identity-checked registry mutations, rollback on partial registration failure, and awaited removal in the `if_exists="replace"` path.

## Target Files

- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `src/hassette/scheduler/triggers.py`
- modify: `src/hassette/scheduler/classes.py`
- modify: `src/hassette/test_utils/factories.py`
- modify: `src/hassette/test_utils/web_job_helpers.py`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > Registry, Registration, EntityTime Waiting)
- modify: `tests/unit/test_scheduler_resource.py`
- modify: `tests/unit/test_scheduler_job_names.py`
- modify: `tests/unit/core/test_scheduler_service_reschedule.py`
- modify: `tests/integration/test_scheduler.py`
- modify: `tests/integration/test_scheduler_entity_time.py`
- modify: `tests/unit/scheduler/test_scheduler_coroutine_conversion.py`
- modify: `tests/unit/scheduler/test_scheduler_where.py`
- modify: `tests/unit/scheduler/test_scheduler_error_handler.py`
- read: `tests/unit/core/conftest.py`

## Prompt

**Add the live registry** to `SchedulerService`:

- `_jobs_by_id: dict[int, Job]` — populated after persistence assigns `db_id`.
- Every mutation must be identity-checked: `if self._jobs_by_id.get(db_id) is job`.
- `get_all_jobs()` reads from the registry, not the heap.

**Refactor `add_job()`** in `SchedulerService`:
1. Persist the registration and assign `db_id`.
2. Add the job to `_jobs_by_id`.
3. Enqueue only if `schedule_status is SCHEDULED`.

**Implement `Scheduler.register()`:**
- Guarded awaited API (`guard_await()`), required `name=`, same source-location capture.
- Accepts: `group`, `timeout`, `disable_timeout`, `mode`, `on_error`, `args`, `kwargs`, `if_exists`.
- Does NOT accept: `trigger`, `jitter`, `where` (predicate).
- Manual jobs use `schedule_status=MANUAL`, `trigger=None`, `next_run=None`, `fire_at=None`.
- Persists `trigger_type="manual"`, `trigger_label="Manual only"`, `trigger_detail=NULL`.

**Handle manual trigger-type in `add_job()`:**
There is no `TriggerDbType` enum in the codebase. Each trigger class has its own `trigger_db_type() -> Literal[...]` method. `SchedulerService.add_job()` calls `trigger.trigger_db_type()` when `job.trigger is not None`, with an `else` branch (currently "unreachable") that hardcodes `trigger_type = "custom"`. For manual jobs (`job.trigger is None`), this branch becomes reachable — change it to set `trigger_type="manual"`, `trigger_label="Manual only"`, `trigger_detail=None`.

**Extract common job construction** from `schedule()` so `schedule()` and `register()` share policy resolution and `Job` construction. This prevents drift.

**Implement EntityTime waiting:**
- When `EntityTime.first_run_time()` or `next_run_time()` returns `WAITING`, construct/transition the job as `WAITING` instead of assigning a timestamp.
- `Scheduler.schedule()` binds the state reader and calls `first_run_time()` — handle `WAITING` return here.
- `_reschedule_entity_time_job()`: when `trigger.resolve_from_state()` returns `WAITING`, transition to waiting and remove any heap entry without removing the registration or watcher.
- Post-registration reconciliation (`_add_job_and_watch_entity`): handle `WAITING` from `trigger.resolve()`.
- Remove all `NO_OCCURRENCE` references.

**Implement rollback:**
- `Scheduler._add_job()`'s call to `scheduler_service.add_job()` is wrapped in try/except. On exception, call a lightweight cleanup helper that removes the job from registry (`_jobs_by_id`), per-app indexes (`_jobs_by_name`, `_jobs_by_group`), and heap if present. If persistence produced a row ID, set `removed_at`. This helper is a subset of the full unified removal operation (which T05 builds to also handle guard cancellation, queued-execution draining, etc.) — T03's rollback path handles only registration-time failures where no execution has been spawned.

**Implement awaited removal in replace path:**
- `if_exists="replace"` must await the old job's removal persistence before issuing the new registration's upsert. Change `cancel_job(existing)` in `_add_job()` to await the persistence write rather than spawning it fire-and-forget.

**Implement owner cleanup:**
- `Scheduler._remove_all_jobs()` passes its own `_jobs_by_name` values to `SchedulerService.remove_jobs(jobs: list[Job])` for identity-checked per-job removal.

**Update test utilities:**
- `src/hassette/test_utils/factories.py`: rename `ScheduledJob` references, update `make_scheduled_job` factory, update mock `cancel_job`/`dequeue_job`/`add_job`/`reschedule_job` references.
- `src/hassette/test_utils/web_job_helpers.py`: rename `ScheduledJob` references.

**Update existing tests** to use `Job`, `remove_job()`, `remove_group()`, remove `NO_OCCURRENCE` assertions, add waiting-state transition tests.

See design doc: Architecture > Registry Separate From Heap, Registration, EntityTime Waiting.

## Focus

- `EntityTime.resolve()` currently returns `NO_OCCURRENCE` — it must now return `WAITING`. But `resolve()` is also called in the reconciliation path in `_add_job_and_watch_entity` as `trigger.resolve(date_utils.now()) or NO_OCCURRENCE`. The `or` pattern must change since `WAITING` is truthy — use explicit `if result is WAITING` checks.
- The `_pending_next_run` mechanism in `scheduler_service.py` must be replaced with a pending EntityTime transition that can represent either a concrete time or `WAITING`.
- `Scheduler._on_job_removed` callback must identity-check `_jobs_by_name`/`_jobs_by_group` pops.
- The `register_removal_callback` docstring in `scheduler_service.py` documents the crash-restart orphan scenario — the identity guard prevents this.
- `tests/integration/test_scheduler_entity_time.py` currently asserts `NO_OCCURRENCE` for unavailable entity times — replace with waiting-state assertions.
- `tests/unit/core/conftest.py` mocks `_job_queue` — verify the mock still works after registry addition.

## Verify

- [ ] FR#1: `await scheduler.register(func, name="test")` returns a `Job` with `schedule_status == "manual"` and a valid `db_id`.
- [ ] FR#2: `register()` accepts group, timeout, mode, error handler, args/kwargs, if_exists. Rejects trigger, jitter, predicate.
- [ ] FR#5: `SchedulerService._jobs_by_id` contains every live job, independent of heap membership.
- [ ] FR#6: The heap contains only jobs with `schedule_status == SCHEDULED` and concrete timing.
- [ ] FR#7: An `EntityTime` job with unavailable source is `WAITING`, registered, watched, and outside the heap.
- [ ] FR#8: An `EntityTime` job transitions between `WAITING` and `SCHEDULED` when its entity value changes, without losing registration or missing a change during setup.
- [x] FR#20: `if_exists="replace"` awaits the old job's removal write before the new upsert. Replacement failure leaves no old registration and no partial new one. Covered by `test_replace_failure_leaves_no_old_and_no_partial_new` and `test_rollback_removes_generic_job_after_post_persist_failure` in `tests/unit/test_scheduler_job_names.py`.
- [x] FR#21: `remove_all_jobs()` removes every owned job including waiting, completed, and manual jobs. (CONTESTED, resolved 2026-07-31: initial implementation covered only the normal shutdown path; `AppLifecycleService.cleanup_failed_instance()`'s reload/failure-cleanup path called the heap-only `remove_jobs_by_owner()`, missing waiting/completed/manual jobs. Fixed by routing that call site through `Scheduler.remove_all_jobs()` — renamed public during this fix since it now has 3+ cross-file callers — the same registry-aware path used for normal shutdown.)
- [ ] AC#1: Tests demonstrate `register()` returns a persisted `Job` with manual status and no heap entry.
- [ ] AC#2: Tests demonstrate waiting EntityTime registration, invalid/valid transitions, watcher cleanup, and race reconciliation.
