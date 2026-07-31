# Context: Registered and Manual Jobs

## Problem & Motivation

Hassette's scheduler treats heap presence as proof a job exists. This prevents a registered job from existing without an automatic occurrence — `EntityTime` works around this with a year-9999 `NO_OCCURRENCE` sentinel, completed one-shots vanish from runtime state, and app authors needing manually invoked work must invent a fake schedule. Manual execution is also coupled to heap membership: the Python API has no manual-only registration, and the web Run Now route can only address heap-resident jobs. The scheduler needs to distinguish a live job registration from its optional automatic schedule without becoming a generic workflow platform.

## Visual Artifacts

None.

## Key Decisions

1. **One `Job` type, no subclasses.** Rename `ScheduledJob` to `Job`. Both `schedule()` and new `register()` construct it. Ownership, invocation policy, telemetry, grouping, removal, and execution are identical for scheduled and manual jobs.
2. **Registry separate from heap.** `SchedulerService._jobs_by_id` is the authority for live runtime existence. The heap contains only jobs with concrete automatic occurrences. Global inspection and manual submission resolve from the registry.
3. **Four-value `ScheduleStatus` enum** (`scheduled`, `waiting`, `completed`, `manual`) on `Job`, with a typed `ScheduleStatusReason` enum (`LEGACY_UNKNOWN`, `TRIGGER_ERROR`, or `None`).
4. **`Job.transition_to(status, *, next_run, fire_at, reason)`** centralizes all status transitions, enforcing the pairing between status and timing fields.
5. **Typed `WAITING` sentinel** replaces `NO_OCCURRENCE`. Both `first_run_time()` and `next_run_time()` can return it. `TriggerProtocol` return types widen to accommodate it.
6. **Fire-and-observe `submit()`** — `Job.submit()` returns `None`, uses registered args, bypasses predicates. Same path for Python, API, CLI, UI.
7. **Removal replaces cancellation** for registration lifecycle. `cancel()` → `remove()`, `cancelled_at` → `removed_at`. Cancellation remains only for interrupted execution.
8. **Identity-checked registry mutations** — every insertion/removal from `_jobs_by_id`, `_jobs_by_name`, `_jobs_by_group` checks object identity to prevent crash-restart orphan collisions.
9. **Awaited removal in replace path** — `if_exists="replace"` awaits the old job's removal persistence before the new upsert, preventing write-ordering races on the shared natural-key row.
10. **Run Now feedback** — frontend polls for execution records post-submission; timeout fallback for suppressed/dropped invocations (FR#26). Follow-up issue #1491 for correlation ID.

## Constraints & Anti-Patterns

- Do NOT add a generic execution service, executable registry, producer adapter layer, or request queue.
- Do NOT refactor Bus registration or invocation behavior (the `listeners.cancelled_at` → `removed_at` rename is a mechanical terminology correction, not a behavioral change).
- Do NOT expose callable return values, waiting invocation, invocation handles, or execution result objects.
- Do NOT add per-submission arguments or predicate override flags.
- Do NOT infer live registration from heap membership.
- Do NOT encode waiting as a far-future timestamp.
- Do NOT combine registration, schedule, and execution into one runtime state enum.
- Do NOT retain compatibility aliases for `ScheduledJob` or cancellation API names.
- Do NOT generalize `TriggerProtocol` for arbitrary recoverable triggers — `WAITING` is EntityTime-specific.

## Design Doc References

- `## Architecture` — the six subsections define the runtime model, registration flow, EntityTime waiting, completion, manual submission, and removal.
- `## Functional Requirements` — FR#1-FR#26, the binding contract for implementation.
- `## Edge Cases` — 14 specific scenarios the implementation must handle.
- `## Migration` — forward-only SQLite migration (012.sql), FK-parent rebuild safety, legacy backfill.
- `## Operator Surfaces` — API enrichment, CLI formatting, frontend rendering rules for all four statuses.
- `## Test Strategy` — required test types, existing tests to adapt, new coverage, tests to remove.
- `## Documentation Updates` — 15+ doc files to update, including snippet `.py` files outside type-check coverage.
- `## Convention Examples` — 5 real code snippets showing patterns to preserve.

## Convention Examples

### Guarded awaited registration

**Source:** `src/hassette/scheduler/scheduler.py`

```python
return guard_await(
    self._add_job_and_watch_entity(job, trigger, if_exists=if_exists),
    owner=self.parent,
    source_location=source_location,
    method_name="schedule",
)
```

### Service-owned fire-and-observe dispatch

**Source:** `src/hassette/web/routes/scheduler.py`

```python
scheduler_service.task_bucket.spawn(
    scheduler_service.run_job_with_guard(job, trigger_mode="manual"),
    name="scheduler:manual_trigger",
)
```

### Shared overlap execution path

**Source:** `src/hassette/core/scheduler_service.py`

```python
await run_through_guard(
    guard=job.guard,
    spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name),
    pending_done=job.pending_done,
    invoke=lambda: self.run_job(job, trigger_mode=trigger_mode),
    warn=lambda secs: self.warn_stalled_job(job, secs),
    spawn_name="scheduler:mode_invocation",
    threshold=STALL_THRESHOLD_SECONDS,
)
```

### EntityTime registration reconciliation

**Source:** `src/hassette/scheduler/scheduler.py`

```python
current = trigger.resolve(date_utils.now()) or NO_OCCURRENCE
if current != job.next_run:
    await self.scheduler_service.reschedule_job(job, current)
```

### Live operator enrichment

**Source:** `src/hassette/web/utils.py`

```python
live_by_db_id = {job.db_id: job for job in live_jobs if job.db_id is not None}

for js in db_jobs:
    live_job = live_by_db_id.get(js.job_id)
    if live_job is not None:
        guard = live_job.guard
        enriched.append(
            js.model_copy(
                update={
                    "next_run": live_job.next_run.timestamp(),
                    "fire_at": live_job.fire_at.timestamp() if live_job.jitter is not None else None,
                    "jitter": live_job.jitter,
                    "suppressed_count": guard.suppressed,
                    "dropped_count": guard.dropped,
                }
            )
        )
```
