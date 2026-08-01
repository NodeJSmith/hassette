# Job Management

`schedule()`, `register()`, and all convenience methods return a [`Job`][hassette.scheduler.classes.Job]. This page covers schedule status, removal, groups, jitter, error handling, and job metadata for live jobs.

## Schedule status

Every live job carries a `schedule_status` — what it's doing right now, independent of whether it has ever run:

| Status | Meaning |
|---|---|
| `scheduled` | Has a concrete next automatic occurrence. |
| `waiting` | An [`EntityTime`](triggers.md#entity-driven-times) job whose source entity currently names no usable time. Stays registered and watched; reactivates when the entity's value becomes usable again. |
| `completed` | Every automatic occurrence has fired, or the trigger raised while computing the next one. The job stays live and can still be submitted manually. |
| `manual` | Registered via `register()` with no trigger at all. Never fires on its own. |

`schedule_status` is not the same as "has this job ever run." A `completed` job that has never been submitted manually is still `completed` — completion tracks the automatic schedule, not execution history. The [monitoring UI](../../web-ui/index.md) shows the status directly instead of a fabricated or blank next-run time.

## Remove a job

`job.remove()` removes the job's registration immediately. The job does not fire again, on any schedule status.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_remove_job.py"
```

Calling `remove()` on an already-removed job is a silent no-op. The scheduler checks dequeue state at entry and returns immediately if the job is already gone.

## Check whether a job is active

`Job` has no `removed` attribute. Removal takes the job out of the scheduler's internal index. The canonical check is membership in `list_jobs()`:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:is_running"
```

For the common case of guarding against a double-remove, storing `None` after removal is simpler and avoids the `list_jobs()` scan:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:remove_null"
```

## Jobs stop automatically when the app stops

Hassette removes every job created by an app — scheduled, waiting, completed, or manual — when that app stops or reloads. Manual removal is only necessary to stop a job while the app is still running.

## Group related jobs

The `group=` parameter assigns a job to a named group at registration time. A named group can be removed or listed as a unit.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_groups.py"
```

`list_jobs(group=group)` returns all live jobs in the group. `list_jobs()` without `group=` returns all jobs for the app instance.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:list_jobs"
```

`remove_group(group)` removes every job in a named group. Each member is individually removed and recorded as removed in the database. The call is a no-op when the group does not exist.

## Stop a job from inside its handler

A job can remove itself from inside its own handler. The `Job` reference is stored on the app instance so the handler can reach it:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_self_remove.py"
```

`remove()` removes the job from the queue immediately. If the dispatch loop has already picked up the job for execution, it checks dequeue state after acquiring the job and skips the handler. Double-execution cannot occur.

## Run a job on demand: `submit()`

`job.submit()` runs the job's callable immediately, using its registered `args`/`kwargs`, and returns `None` without waiting for the invocation to finish. It bypasses the job's predicate and never touches its automatic schedule — a pending one-shot still fires at its original time even after a manual submission, and a `waiting`/`completed`/`manual` job stays at that status.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_register_manual.py:submit"
```

`submit()` goes through the same overlap guard as an automatic fire. A `single`-mode job already running suppresses the submission; a full `queued` cap drops it. Both outcomes are recorded in telemetry, not raised as an exception — `submit()` always accepts a live job. The [Execution Modes](execution-modes.md#manual-submission) page covers overlap behavior for manual submissions in detail.

Submitting a removed job's handle raises `JobRemovedError`. The [Run Now button](../../web-ui/debug-handler.md) in the monitoring UI, and the REST API it calls, use the same submission path — see [Scheduler Overview](index.md#register-a-job-with-no-automatic-schedule) for registering a manual-only job.

## Prevent overlapping executions

App jobs run in `single` mode by default, which prevents a recurring job from
running twice at once. When the next tick becomes due while the prior invocation
is still running, the scheduler drops the re-fire and logs it at DEBUG.
Framework-internal jobs default to `parallel` — see
[Execution Modes](execution-modes.md#default-mode-tier-aware).

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

No manual lock is needed. App jobs default to `single`, so the example above
already prevents overlap. [Execution Modes](execution-modes.md) covers all four
overlap behaviors — `single`, `restart`, `queued`, and `parallel` — including
how to serialize every tick (`queued`) or allow concurrent runs (`parallel`).

??? note "Manual lock pattern (pre-1.0)"
    Before execution modes were introduced, the recommended approach was an
    `asyncio.Lock` to prevent concurrent runs:

    ```python
    --8<-- "pages/core-concepts/scheduler/snippets/scheduler_overlapping_jobs.py"
    ```

    The `single` default makes this unnecessary for new code. The lock pattern
    remains valid if you need it, but the mode parameter is simpler and surfaces
    overlap activity in the monitoring UI.

## Handle errors

On exception, Hassette logs the error, records it for telemetry, and keeps the job on its normal schedule. An optional error handler receives a typed [`SchedulerErrorContext`][hassette.scheduler.error_context.SchedulerErrorContext] with full exception details.

### App-level handler

`scheduler.on_error(handler)` registers a fallback handler for all jobs on this scheduler that lack a per-registration handler. The handler resolves at dispatch time, not at registration time.

!!! warning "Registration order matters"
    `on_error()` must run before any job is registered in `on_initialize()`. For example, if you call `run_in(handler, delay=1)` before `on_error()`, and the job fires within that 1-second window while `on_initialize()` is still running, no error handler is registered for that execution.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_error_handler_app.py"
```

### Per-job handler

The `on_error=` parameter on any scheduling method takes precedence over the app-level handler.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_error_handler_per_job.py"
```

Both levels accept sync or async callables.

### Fields in the error handler

| Field | Type | Description |
|---|---|---|
| `exception` | `BaseException` | The raised exception. |
| `traceback` | `str` | Full formatted traceback string. |
| `job_name` | `str` | Human-readable job name. |
| `job_group` | `str \| None` | Group name if the job was registered with `group=`. |
| `args` | `tuple[Any, ...]` | Positional arguments the job was scheduled with. |
| `kwargs` | `dict[str, Any]` | Keyword arguments the job was scheduled with. |

!!! note "Error handler failures"
    When an error handler itself raises or times out, Hassette logs the failure and counts it against the executor's error handler failure counter. The original job's telemetry record is unaffected.

## Tune dispatch with jitter

The `jitter=` parameter adds a random offset to a job's dispatch time. The offset is drawn uniformly from `[0, jitter)` seconds and applied at enqueue time.

Jitter affects dispatch order within the heap. The logical `next_run` timestamp on the job remains unchanged — a job scheduled every 60 seconds targets T+60, T+120, T+180 regardless of jitter. The random offset shifts the actual dispatch within each window but does not compound across runs.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_jitter.py:jitter"
```

Jitter is useful when several apps schedule work at the same wall-clock time and concurrent execution would cause contention.

## Inspect a job's metadata

`Job` exposes read-only metadata set at registration time and updated by the scheduler as the job runs.

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name. Auto-generated from the callable and trigger when not provided. Appears in logs; idempotent re-registration matches on this name. |
| `schedule_status` | `ScheduleStatus` | One of `scheduled`, `waiting`, `completed`, `manual`. See [Schedule status](#schedule-status). |
| `next_run` | `ZonedDateTime \| None` | Unjittered logical fire time. `None` for every status except `scheduled`. Subsequent trigger calculations use this as `previous_run`. |
| `trigger` | `TriggerProtocol \| None` | The trigger that drives scheduling. `None` for a manual-only job. |
| `group` | `str \| None` | Group name, set when the job was registered with `group=`. `remove_group()` uses this for bulk removal. |
| `jitter` | `float \| None` | Seconds of random offset applied at enqueue time, if configured. |
| `fire_at` | `ZonedDateTime \| None` | Actual dispatch time including the jitter offset. Equals `next_run` when `jitter` is not set. `None` for every status except `scheduled`. |
| `db_id` | `int \| None` | Database row ID assigned after registration. Valid immediately when the scheduling call returns. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py"
```

## Troubleshooting

??? note "Troubleshooting scheduled jobs"
    ### Job not running?

    - **Wrong schedule.** A wrong time string or interval is the most common cause. `run_daily(at="07:00")` fires at 7 AM. `run_once(at="07:00")` fires at 7 AM today, or tomorrow if 7 AM has already passed.
    - **Unhandled exception.** When a job raises, the scheduler catches it, logs at `ERROR`, and keeps the job on schedule. The job is not removed. Look for `ERROR hassette.CommandExecutor` lines followed by a traceback.
    - **Lost reference.** Losing the `Job` variable does not stop the job. The scheduler holds a strong reference. Losing the reference only prevents manual removal.
    - **Job is `completed`.** A finite trigger (`run_in`, `run_once`, or a custom trigger whose `next_run_time()` returned `None`) has fired its last occurrence. The job stays live and submit-capable — check `job.schedule_status` or the monitoring UI rather than assuming a missing next run means the job vanished.

    ### Job runs too often?

    - **Wrong units.** `run_every(seconds=5)` is 5 seconds. `run_every(minutes=5)` is 5 minutes.
    - **Wrong cron expression.** `run_cron("5 * * * *")` fires at minute 5 of every hour. `run_cron("*/5 * * * *")` fires every 5 minutes.

## See Also

- [Scheduling Methods](methods.md) for registration options, `register()`, `if_exists`, and per-job parameters
- [Triggers](triggers.md) for built-in trigger types, `EntityTime` waiting, and writing custom triggers
- [Apps Lifecycle](../apps/lifecycle.md) for how shutdown triggers automatic job cleanup
