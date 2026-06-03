# Job Management

`schedule()` and all convenience methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob]. The object carries metadata about the job and provides the primary cancellation method.

## The `ScheduledJob` Object

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name. Auto-generated from the callable and trigger when not provided. Appears in logs and serves as the key for idempotent re-registration. |
| `next_run` | `ZonedDateTime` | Unjittered logical fire time. Subsequent trigger calculations use this as `previous_run`. |
| `trigger` | `TriggerProtocol \| None` | The trigger that drives scheduling. |
| `group` | `str \| None` | Group name, set when the job was registered with `group=`. `cancel_group()` uses this for bulk cancellation. |
| `jitter` | `float \| None` | Seconds of random offset applied at enqueue time, if configured. |
| `db_id` | `int \| None` | Database row ID assigned after registration. Valid immediately when the scheduling call returns. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py"
```

## Cancelling Jobs

`job.cancel()` removes the job from the scheduler queue immediately. The job does not fire again.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_cancel_job.py"
```

Calling `cancel()` on an already-cancelled job is a silent no-op. The scheduler checks dequeue state at entry and returns immediately if the job is already gone.

### Cancelling Groups

`cancel_group(group)` cancels every job in a named group. Each member is individually dequeued and recorded as cancelled in the database. The call is a no-op when the group does not exist.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:cancel_group"
```

### Listing Jobs

`list_jobs()` returns all active jobs on this scheduler. `list_jobs(group=)` filters to a named group.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:list_jobs"
```

### Checking Whether a Job Is Active

`ScheduledJob` has no `cancelled` attribute. Cancellation removes the job from the scheduler's internal index, so the canonical check is membership in `list_jobs()`:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:is_running"
```

For the common case of guarding against a double-cancel, storing `None` after cancellation is simpler and avoids the `list_jobs()` scan:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_management_patterns.py:cancel_null"
```

## Automatic Cleanup

Hassette cancels all jobs created by an app when that app stops or reloads. Manual cancellation is only necessary to stop a job while the app is still running.

## Self-Cancelling Jobs

A job can cancel itself from inside its own handler. The `ScheduledJob` reference is stored on the app instance so the handler can reach it:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_self_cancel.py"
```

`cancel()` removes the job from the queue immediately. If the dispatch loop has already picked up the job for execution, it checks dequeue state after acquiring the job and skips the handler. Double-execution cannot occur.

## Avoiding Overlapping Executions

When a handler takes longer than its interval, the scheduler launches a new execution before the previous one finishes. An `asyncio.Lock` prevents concurrent runs:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_overlapping_jobs.py"
```

The locked check at entry skips the tick rather than queuing behind it.

## Error Handling

When a scheduled job raises an exception, Hassette logs the error, records it for telemetry, and keeps the job on its normal schedule. An optional error handler receives a typed [`SchedulerErrorContext`][hassette.scheduler.error_context.SchedulerErrorContext] with full exception details.

### App-Level Error Handler

`scheduler.on_error(handler)` registers a fallback handler for all jobs on this scheduler that lack a per-registration handler. The handler resolves at dispatch time, not at registration time.

!!! warning "Registration order matters"
    `on_error()` should be the first statement in `on_initialize()`. A job that fires before `on_error()` is called has no handler for that execution.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_error_handler_app.py"
```

### Per-Registration Error Handler

The `on_error=` parameter on any scheduling method takes precedence over the app-level handler.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_error_handler_per_job.py"
```

Both levels accept sync or async callables.

### What `SchedulerErrorContext` Contains

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

??? note "Job not running?"
    - **Wrong schedule.** A wrong time string or interval is the most common cause. `run_daily(at="07:00")` fires at 7 AM. `run_once(at="07:00")` fires at 7 AM today, or tomorrow if 7 AM has already passed.
    - **Unhandled exception.** When a job raises, the scheduler catches it, logs at `ERROR`, and keeps the job on schedule. The job is not removed. Look for `ERROR hassette.core.command_executor` lines followed by a traceback.
    - **Lost reference.** Losing the `ScheduledJob` variable does not stop the job. The scheduler holds a strong reference. Losing the reference only prevents manual cancellation.

??? note "Job runs too often?"
    - **Wrong units.** `run_every(seconds=5)` is 5 seconds. `run_every(minutes=5)` is 5 minutes.
    - **Wrong cron expression.** `run_cron("5 * * * *")` fires at minute 5 of every hour. `run_cron("*/5 * * * *")` fires every 5 minutes.

## See Also

- [Scheduling Methods](methods.md) for registration options, `if_exists`, and per-job parameters
- [Triggers](triggers.md) for built-in trigger types and writing custom triggers
- [Apps Lifecycle](../apps/lifecycle.md) for how shutdown triggers automatic job cleanup
