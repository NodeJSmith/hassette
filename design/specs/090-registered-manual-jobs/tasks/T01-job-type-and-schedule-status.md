---
task_id: "T01"
title: "Rename ScheduledJob to Job and add schedule status"
status: "planned"
depends_on: []
implements: ["FR#3", "FR#4", "FR#10", "FR#16", "FR#18"]
---

## Summary

Rename `ScheduledJob` to `Job` in `src/hassette/scheduler/classes.py`. Add the `ScheduleStatus` and `ScheduleStatusReason` enums and the `transition_to()` method that centralizes all status/timing mutations. Make `next_run` and `fire_at` optional. Add `schedule_status` and `schedule_status_reason` fields. Add `Job.submit()` and `Job.remove()` handle methods (delegating to service — stubbed until T03/T04). Add `JobRemovedError` to `src/hassette/exceptions.py`. Rename public removal APIs on `Scheduler`. Update `__init__.py` exports, `TriggerProtocol` return types, and all direct importers of the old name.

## Target Files

- modify: `src/hassette/scheduler/classes.py`
- modify: `src/hassette/scheduler/__init__.py`
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `src/hassette/scheduler/triggers.py`
- modify: `src/hassette/types/types.py`
- modify: `src/hassette/commands.py`
- modify: `src/hassette/exceptions.py`
- modify: `src/hassette/core/state_proxy.py`
- modify: `src/hassette/execution_mode.py`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > One Scheduler-Owned Job)
- modify: `tests/unit/test_scheduled_job.py`
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py`
- modify: `tests/unit/scheduler/test_scheduled_job_timeout.py`
- modify: `tests/unit/scheduler/test_scheduled_job_mark_registered.py`
- modify: `tests/unit/test_source_tier_models.py`
- modify: `tests/unit/test_source_tier_propagation.py`
- modify: `tests/unit/types/test_service_protocols.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `tests/pyright_probes/forgotten_await_probe.py`
- modify: `tests/unit/resources/lifecycle/test_init.py`
- modify: `tests/unit/resources/lifecycle/test_force_terminal.py`

## Prompt

Rename `ScheduledJob` to `Job` in `src/hassette/scheduler/classes.py`. This is the foundational type change — every other task depends on it.

**Add enums** (in `classes.py` or a new `src/hassette/scheduler/enums.py` if cleaner):

```python
class ScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    COMPLETED = "completed"
    MANUAL = "manual"

class ScheduleStatusReason(StrEnum):
    LEGACY_UNKNOWN = "legacy_unknown"
    TRIGGER_ERROR = "trigger_error"
```

**Add `transition_to()`** on `Job`:
- Signature: `transition_to(self, status: ScheduleStatus, *, next_run: ZonedDateTime | None = None, fire_at: ZonedDateTime | None = None, reason: ScheduleStatusReason | None = None)`
- `SCHEDULED` requires concrete `next_run`; all other statuses clear timing fields to `None`.
- Sets `schedule_status`, `next_run`, `fire_at`, and `schedule_status_reason` atomically.
- Updates `sort_index` only when `next_run` is set.

**Make timing optional**: `next_run` and `fire_at` become `ZonedDateTime | None` on `Job`. `_ScheduledJobQueue.add()` already rejects jobs without timing — verify this guard still works.

**Add handle methods** on `Job`:
- `submit(self) -> None` — delegates to `self._scheduler_service.submit_job(self)` (the service method is implemented in T03).
- `remove(self) -> None` — delegates to the removal path (implemented in T04).

**Add `JobRemovedError`** to `src/hassette/exceptions.py`.

**Rename removal APIs** on `Scheduler`:
- `cancel_job()` → `remove_job()`
- `cancel_group()` → `remove_group()`
- Internal `_on_job_removed` callback: identity-check `_jobs_by_name` and `_jobs_by_group` pops (`self._jobs_by_name.get(job.name) is job`).

**Add WAITING sentinel** to `src/hassette/scheduler/triggers.py`:
- Remove `NO_OCCURRENCE`.
- Add a typed `WAITING` sentinel (module-level constant with a distinct type, e.g. `class _WaitingSentinel` with a singleton `WAITING = _WaitingSentinel()`).
- Widen `TriggerProtocol.first_run_time()` return type to `ZonedDateTime | _WaitingSentinel`.
- Widen `TriggerProtocol.next_run_time()` return type to `ZonedDateTime | None | _WaitingSentinel`.
- Update `EntityTime.resolve()` to return `WAITING` instead of `NO_OCCURRENCE` when the source is unavailable.

**Update imports** in `__init__.py`, `commands.py`, `types.py` (`SchedulerServiceProtocol.mark_job_cancelled` → `mark_job_removed`), `state_proxy.py`, `execution_mode.py`.

**Update all unit tests** that reference `ScheduledJob` by name, `cancel_job`, `cancel_group`, or `NO_OCCURRENCE`. The listed test files are the known set; grep for `ScheduledJob` to catch any others.

See design doc: Architecture > One Scheduler-Owned Job, Architecture > EntityTime Waiting, Replacement Targets.

## Focus

- `_ScheduledJobQueue` in `scheduler_service.py` uses `job.next_run` for heap ordering — verify the `add()` guard rejects jobs with `next_run is None`.
- `state_proxy.py` has `poll_job: "ScheduledJob | None"` field — rename to `Job`.
- `execution_mode.py` references `ScheduledJob` in type hints.
- `tests/unit/resources/lifecycle/test_init.py` has `_ScheduledJobQueue` in `LEAF_TYPES` — update the string.
- `tests/unit/types/test_service_protocols.py` asserts `mark_job_cancelled` exists on the protocol — change to `mark_job_removed`.
- `tests/pyright_probes/forgotten_await_probe.py` references scheduler types.
- Do NOT touch `scheduler_service.py` heap/registry logic yet — that's T03. Do NOT touch persistence — that's T02. Only rename the type, add the enums/methods, and update importers.

## Verify

- [ ] FR#3: `Scheduler.schedule()` and `Scheduler.register()` (stubbed) both return `Job`, not `ScheduledJob`. `ScheduledJob` no longer exists as a public name.
- [ ] FR#4: `Job` has a `schedule_status` field typed as `ScheduleStatus` with exactly four values.
- [ ] FR#10: A `Job` constructed with `schedule_status=MANUAL` has `trigger=None`, `next_run=None`, `fire_at=None`.
- [ ] FR#16: `JobRemovedError` exists in `src/hassette/exceptions.py`.
- [ ] FR#18: `Scheduler` exposes `remove_job()` and `remove_group()`, not `cancel_job()`/`cancel_group()`.
