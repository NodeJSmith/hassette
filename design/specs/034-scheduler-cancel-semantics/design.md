# Design: Clarify Cancel vs Remove Job Semantics

**Date:** 2026-04-17
**Status:** approved
**Spec:** design/specs/034-scheduler-cancel-semantics/spec.md
**Research:** /tmp/claude-mine-design-research-jx7LB6/brief.md

## Problem

The Scheduler has two overlapping public methods for stopping jobs (`remove_job` and `cancel_job`), a transient `cancelled` flag on `ScheduledJob` that appears load-bearing but is vestigial, and a `job.cancel()` method that performs an incomplete cancellation (flag-only, no dequeue or DB persist). This creates user confusion about which method to call, dead-code dispatch guards that obscure the real control flow, and an enrichment OR expression that papers over an async race.

## Architecture

### Back-reference and cancel delegation

`ScheduledJob` gains a `_scheduler` field:

```python
_scheduler: "Scheduler | None" = field(default=None, repr=False, compare=False)
_dequeued: bool = field(default=False, repr=False, compare=False)
```

Set in `Scheduler.add_job()` (`job._scheduler = self`) **before** calling `scheduler_service.add_job(job)`, so the back-reference is available before the job enters the heap. `ScheduledJob.cancel()` becomes:

```python
def cancel(self) -> None:
    if self._scheduler is None:
        raise RuntimeError(
            "cancel() called on a job not registered with a Scheduler. "
            "Use Scheduler.cancel_job(job) or register the job first."
        )
    self._scheduler.cancel_job(self)
```

`Scheduler.cancel_job()` is the implementation target — it must NOT call `job.cancel()` internally. Its body:

```python
def cancel_job(self, job: ScheduledJob) -> None:
    if job._dequeued:
        return  # idempotent — already cancelled
    if job._scheduler is not self:
        raise ValueError(
            f"cancel_job() called with a job belonging to a different scheduler "
            f"(job owner: {job._scheduler}, this scheduler: {self})"
        )
    if job.db_id is not None:
        self.task_bucket.spawn(
            self.scheduler_service.mark_job_cancelled(job.db_id),
            name="scheduler:mark_job_cancelled",
        )
    self._dequeue_job(job)
    # Mark as dequeued — signals to _dispatch_and_log that this job
    # was cancelled between heap-pop and dispatch (see race guard below).
    # Back-reference preserved for debugging/telemetry.
    job._dequeued = True
```

### Synchronous dequeue

`Scheduler.remove_job` is renamed to `_dequeue_job`. It calls a new synchronous method `SchedulerService.dequeue_job(job)` which performs an inline heap removal without spawning an async task or acquiring the async lock.

This is safe because:
- All scheduler operations run on the same event loop thread (single-threaded asyncio).
- `HeapQueue.remove_item()` is a pure synchronous operation (`list.remove()` + `heapq.heapify()`) with no await points.
- No other coroutine can touch the heap between the call and return.

The existing async task-spawning `SchedulerService.remove_job` (line 493) is removed — it has zero callers after this refactor. The internal `SchedulerService._remove_job` (async, acquires lock) is retained for serve-loop paths (job exhaustion, trigger errors in `reschedule_job`).

A new synchronous `remove_item_sync(job)` method is added to `_ScheduledJobQueue` to preserve encapsulation (rather than piercing through to `_queue.remove_item()` directly):

```python
# _ScheduledJobQueue — new synchronous method
def remove_item_sync(self, job: ScheduledJob) -> bool:
    """Synchronously remove a job from the heap without acquiring the async lock.

    Safe because HeapQueue.remove_item() is a pure synchronous operation
    (list.remove + heapify) and all scheduler operations run on the same
    event loop thread — no await points, no yield to the event loop.
    """
    return self._queue.remove_item(job)
```

```python
# SchedulerService — new synchronous method
def dequeue_job(self, job: ScheduledJob) -> bool:
    """Synchronously remove a job from the heap. No async lock, no task spawn.

    Fires removal callbacks so _on_job_removed handles dict cleanup —
    all removal paths (cancel, exhaustion, shutdown) go through the same
    callback, making it the single authority for dict state.
    """
    removed = self._job_queue.remove_item_sync(job)
    if removed:
        self.logger.debug("Dequeued job: %s", job)
        self.kick()
    else:
        self.logger.debug("Job not in heap (already popped by serve loop): %s", job)
    # Fire callbacks unconditionally — even when the job was already popped
    # from the heap by the serve loop, dict cleanup (_on_job_removed) must
    # still run to prevent stale entries in _jobs_by_name/_jobs_by_group.
    self._fire_removal_callbacks([job])
    return removed
```

```python
# Scheduler._dequeue_job (renamed from remove_job)
def _dequeue_job(self, job: ScheduledJob) -> bool:
    return self.scheduler_service.dequeue_job(job)
```

Dict cleanup (`_jobs_by_name`, `_jobs_by_group`) is handled exclusively by the `_on_job_removed` callback, which `dequeue_job` fires via `_fire_removal_callbacks`. This makes the callback the single authority for dict state — all removal paths (cancel, exhaustion, shutdown) go through the same callback. No inline dict cleanup in `cancel_job` or `_dequeue_job`.

### cancel_group delegation

`cancel_group` delegates to `cancel_job` per-member instead of inlining the sequence:

```python
def cancel_group(self, group: str) -> None:
    jobs = list(self._jobs_by_group.get(group, set()))
    for job in jobs:
        self.cancel_job(job)  # handles DB write, dequeue; callback handles dict cleanup
```

### Removing the cancelled flag and dispatch guards

With `job.cancel()` delegating to a full cancel (synchronous dequeue + DB write), the transient `cancelled` flag on `ScheduledJob` and its dispatch-path guards are replaced by a back-reference check.

**Race window:** The serve loop pops a job from the heap into a local `due_jobs` list, then spawns dispatch tasks. Between the spawn and the task executing, `cancel_job` can run and dequeue the job — but it's already been popped. The dispatch task would then run the handler on a cancelled job. To guard against this, `cancel_job` sets `job._dequeued = True` after dequeue, and `_dispatch_and_log` checks `if job._dequeued: return` before executing. This replaces the old `if job.cancelled` guard with a dedicated lifecycle flag — the back-reference is preserved for debugging and telemetry.

**Double-cancel idempotency:** `cancel_job` checks `if job._dequeued: return` at entry — a second cancel on the same job is a silent no-op, not an error. This matches user expectations (HA automations often cancel from multiple code paths).

Remove:
- `ScheduledJob.cancelled: bool` field
- `ScheduledJob.cancel()` flag-setting logic (replaced by delegation)
- The `if job.cancelled` guards in `run_job` and `reschedule_job` (redundant — the `_dispatch_and_log` guard catches the race at the entry point)
- The `matches()` docstring reference to `cancelled` as a non-compared field

Replace:
- The `if job.cancelled` guard in `_dispatch_and_log` → `if job._dequeued` (set by `cancel_job` after dequeue)

### Telemetry enrichment simplification

`telemetry.py:255` simplifies from `is_cancelled = live_job.cancelled or js.cancelled` to `is_cancelled = js.cancelled` (DB-only via `cancelled_at IS NOT NULL`).

There is a brief window between `cancel_job` being called and `cancelled_at` being committed where telemetry may show the job as active. This is accepted behavior — the window is milliseconds and only affects dashboard polling.

Remove the inline comment at `scheduler.py:192-194` that references the OR-enrichment logic.

### Rename remove_all_jobs

`Scheduler.remove_all_jobs` becomes `_remove_all_jobs`. Return type unchanged (`asyncio.Task`). Callers:
- `Scheduler.on_shutdown` (line 129)
- `test_utils/reset.py` (line 62)
- `test_scheduler_resource.py` (line 247)
- `test_scheduler_job_names.py` (line 94)

Test files calling the underscore-prefixed method directly is consistent with existing patterns (e.g., `hassette._bus_service`).

### Internal callers: StateProxy

`state_proxy.py:87` and `state_proxy.py:291` switch from `self.scheduler.remove_job(self.poll_job)` to `self.scheduler._dequeue_job(self.poll_job)`. These are lifecycle stops (HA disconnect/reconnect), not user cancellations — no `cancelled_at` record should be written.

### web_helpers.py make_job fixture

The `make_job` fixture in `test_utils/web_helpers.py` builds `SimpleNamespace` objects with a `cancelled` parameter. The `JobSummary` model retains its `cancelled: bool` field (DB-derived via `cancelled_at IS NOT NULL`), so web test fixtures still need the parameter. No change required — the fixture's `cancelled` is a `SimpleNamespace` attribute that mirrors `JobSummary`, not `ScheduledJob`.

## Alternatives Considered

### Keep the cancelled flag, only rename remove_job

Smaller scope — just rename `remove_job` to `_dequeue_job` and have `cancel_group` delegate. Don't touch `job.cancel()`, the flag, or the guards.

Rejected because this leaves `job.cancel()` as an incomplete operation (flag-only, no dequeue or DB persist) and keeps the dispatch guards as load-bearing code that obscures the control flow. The back-reference delegation is the key improvement that makes everything else possible.

### Keep the async task-spawning SchedulerService.remove_job alongside the new sync method

Add `dequeue_job` (sync) while keeping `remove_job` (async). Name the sync one `dequeue_job_sync`.

Rejected because after the refactor, `remove_job` has zero external callers. Keeping a dead method creates confusion. The internal `_remove_job` (async, with lock) is retained for serve-loop paths — that's the only async removal needed.

## Test Strategy

**Unit tests:**
- `test_scheduler_resource.py`: Replace `job.cancelled` assertions with behavioral checks (`list_jobs()`, `trigger_due_jobs()` no-op). Rename `remove_job`/`remove_all_jobs` references. Add test verifying `cancel_group` delegates to `cancel_job` per-member.
- `test_scheduler_job_names.py`: Rename `remove_job` → `_dequeue_job`, `remove_all_jobs` → `_remove_all_jobs`.
- `test_scheduler_service_reschedule.py`: Remove/rewrite `reschedule_cancelled_removes_job` — the `job.cancel()` flag-set path no longer exists. Test that an exhausted job is removed via `_remove_job` (internal async path).
- `test_lifecycle_propagation.py`: Rename `remove_all_jobs` in test name and assertions.
- `test_triggers.py`: Replace `scheduled_job.cancel()` with scheduler-based cancel.

**Integration tests:**
- `test_scheduler.py`: Replace `job.cancel()` flag-set calls with scheduler-based cancel. Replace `job.cancelled` assertions with behavioral checks. Add integration test verifying `job.cancel()` via back-reference results in `cancelled_at IS NOT NULL` in the DB.

**No new test infrastructure needed** — existing `list_jobs()`, `trigger_due_jobs()`, and DB assertion patterns are sufficient.

## Open Questions

None — all questions from the research brief were resolved during the spec challenge and design interrogation.

## Impact

### Source files (8 files)

| File | Change |
|------|--------|
| `src/hassette/scheduler/classes.py` | Add `_scheduler` and `_dequeued` fields, remove `cancelled` field, rewrite `cancel()`, update `matches()` docstring |
| `src/hassette/scheduler/scheduler.py` | Rename `remove_job` → `_dequeue_job`, rename `remove_all_jobs` → `_remove_all_jobs`, rewrite `cancel_job` (no `job.cancel()` call), rewrite `cancel_group` (delegate), set back-reference in `add_job`, remove stale OR-enrichment comment |
| `src/hassette/core/scheduler_service.py` | Add `_ScheduledJobQueue.remove_item_sync` (sync method), add `SchedulerService.dequeue_job` (sync method), remove `SchedulerService.remove_job` (async task-spawning wrapper), remove 3 dispatch guards |
| `src/hassette/core/state_proxy.py` | Lines 87, 291: `remove_job` → `_dequeue_job` |
| `src/hassette/web/routes/telemetry.py` | Line 255: simplify to `js.cancelled` only |
| `src/hassette/core/telemetry_models.py` | Update `JobSummary.cancelled` docstring |
| `src/hassette/test_utils/reset.py` | Line 62: `remove_all_jobs` → `_remove_all_jobs` |

### Test files (6 files)

| File | Change |
|------|--------|
| `tests/integration/test_scheduler.py` | Replace `job.cancelled` assertions, add integration test for back-reference cancel |
| `tests/unit/test_scheduler_resource.py` | Rewrite cancel tests, rename methods, add cancel_group delegation test |
| `tests/unit/test_scheduler_job_names.py` | Rename method references |
| `tests/unit/core/test_scheduler_service_reschedule.py` | Remove/rewrite cancelled flag test |
| `tests/unit/resources/test_lifecycle_propagation.py` | Rename `remove_all_jobs` |
| `tests/unit/test_triggers.py` | Replace `scheduled_job.cancel()` |

### Documentation files (2 files requiring changes)

| File | Change |
|------|--------|
| `docs/pages/core-concepts/scheduler/management.md` | Remove `cancelled` from attribute table, update cancel semantics prose, add `list_jobs()` idiom for checking cancellation state |
| `docs/pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py` | Remove `job.cancelled` log line |

### Documentation files confirmed unchanged

Recipe snippets (`motion_lights.py`, `vacation_mode.py`), migration docs, and other scheduler snippets all use `job.cancel()` which remains the primary API — no changes needed.

### Blast radius

Moderate breadth (16 files), low depth per file. No external API changes — `job.cancel()` is the same user-facing call, it just works correctly now. No schema migration. No new dependencies.
