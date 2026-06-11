# Job Management

`schedule()` and all convenience methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob]. This page covers cancellation, groups, jitter, error handling, and job metadata for jobs already scheduled.

## Cancel a job

`job.cancel()` removes the job from the scheduler queue immediately. The job does not fire again.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_cancel_job.py"
```

Calling `cancel()` on an already-cancelled job is a silent no-op. The scheduler checks dequeue state at entry and returns immediately if the job is already gone.

## Check whether a job is active

`ScheduledJob` has no `cancelled` attribute. Cancellation removes the job from the scheduler's internal index. The canonical check is membership in `list_jobs()`:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:is_running"
```

For the common case of guarding against a double-cancel, storing `None` after cancellation is simpler and avoids the `list_jobs()` scan:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:cancel_null"
```

## Jobs stop automatically when the app stops

Hassette cancels all jobs created by an app when that app stops or reloads. Manual cancellation is only necessary to stop a job while the app is still running.

## Group related jobs

The `group=` parameter assigns a job to a named group at registration time. A named group can be cancelled or listed as a unit.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_groups.py"
```

`list_jobs(group=group)` returns all active jobs in the group. `list_jobs()` without `group=` returns all jobs for the app instance.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:list_jobs"
```

`cancel_group(group)` cancels every job in a named group. Each member is individually dequeued and recorded as cancelled in the database. The call is a no-op when the group does not exist.

## Stop a job from inside its handler

A job can cancel itself from inside its own handler. The `ScheduledJob` reference is stored on the app instance so the handler can reach it:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_self_cancel.py"
```

`cancel()` removes the job from the queue immediately. If the dispatch loop has already picked up the job for execution, it checks dequeue state after acquiring the job and skips the handler. Double-execution cannot occur.

## Prevent overlapping executions

The scheduler fires each tick independently — it does not track whether the previous execution has finished. When a handler takes longer than its interval, a new execution starts before the previous one finishes. An `asyncio.Lock` prevents concurrent runs:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_overlapping_jobs.py"
```

The locked check at entry skips the tick rather than queuing behind it.

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

`ScheduledJob` exposes read-only metadata set at registration time and updated by the scheduler as the job runs.

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name. Auto-generated from the callable and trigger when not provided. Appears in logs; idempotent re-registration matches on this name. |
| `next_run` | `ZonedDateTime` | Unjittered logical fire time. Subsequent trigger calculations use this as `previous_run`. |
| `trigger` | `TriggerProtocol \| None` | The trigger that drives scheduling. |
| `group` | `str \| None` | Group name, set when the job was registered with `group=`. `cancel_group()` uses this for bulk cancellation. |
| `jitter` | `float \| None` | Seconds of random offset applied at enqueue time, if configured. |
| `db_id` | `int \| None` | Database row ID assigned after registration. Valid immediately when the scheduling call returns. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py"
```

## Troubleshooting

??? note "Troubleshooting scheduled jobs"
    ### Job not running?

    - **Wrong schedule.** A wrong time string or interval is the most common cause. `run_daily(at="07:00")` fires at 7 AM. `run_once(at="07:00")` fires at 7 AM today, or tomorrow if 7 AM has already passed.
    - **Unhandled exception.** When a job raises, the scheduler catches it, logs at `ERROR`, and keeps the job on schedule. The job is not removed. Look for `ERROR hassette.CommandExecutor` lines followed by a traceback.
    - **Lost reference.** Losing the `ScheduledJob` variable does not stop the job. The scheduler holds a strong reference. Losing the reference only prevents manual cancellation.

    ### Job runs too often?

    - **Wrong units.** `run_every(seconds=5)` is 5 seconds. `run_every(minutes=5)` is 5 minutes.
    - **Wrong cron expression.** `run_cron("5 * * * *")` fires at minute 5 of every hour. `run_cron("*/5 * * * *")` fires every 5 minutes.

## See Also

- [Scheduling Methods](methods.md) for registration options, `if_exists`, and per-job parameters
- [Triggers](triggers.md) for built-in trigger types and writing custom triggers
- [Apps Lifecycle](../apps/lifecycle.md) for how shutdown triggers automatic job cleanup
