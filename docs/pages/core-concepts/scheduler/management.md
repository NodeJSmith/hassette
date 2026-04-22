# Job Management

When you schedule a task, you receive a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] object. You can use this to manage the job's lifecycle.

## The ScheduledJob Object

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name. Auto-generated from the callable and trigger if not provided. Used in logs and for idempotent re-registration. |
| `next_run` | `ZonedDateTime` | Timestamp of the next scheduled execution (unjittered). |
| `trigger` | `TriggerProtocol \| None` | The trigger that drives scheduling. `None` should not occur for jobs created via the public API. |
| `group` | `str \| None` | Group name, if the job was registered with `group=`. Used for bulk cancellation via `cancel_group()`. |
| `jitter` | `float \| None` | Seconds of random offset applied at enqueue time, if specified. |
| `job_id` | `int` | Unique integer identifier assigned at creation. Stable for the lifetime of the job object. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py"
```

## Cancelling Jobs

To stop a job from running, call `cancel()`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_cancel_job.py"
```

### Cancelling Job Groups

Cancel all jobs in a named group at once with `cancel_group()`:

```python
self.scheduler.cancel_group("morning")
```

This cancels each job in the group — removing it from the scheduler queue and recording it as cancelled in the database — then clears the group entry. No-op if the group does not exist.

### Listing Jobs

Query registered jobs with `list_jobs()`:

```python
# All jobs for this app
all_jobs = self.scheduler.list_jobs()

# Only jobs in a specific group
morning_jobs = self.scheduler.list_jobs(group="morning")
```

### Checking Cancellation State

`ScheduledJob` does not expose a `cancelled` attribute. Once a job is cancelled it is removed from the scheduler's queue, so the canonical way to check whether a job is still active is to query `list_jobs()`:

```python
def is_running(self) -> bool:
    return self.my_job in self.scheduler.list_jobs()
```

For the common case of guarding against a double-cancel (for example, when multiple code paths may both call `cancel()`), store the reference as `None` after cancelling and check before calling:

```python
if self.my_job is not None:
    self.my_job.cancel()
    self.my_job = None
```

Calling `cancel()` on an already-cancelled job is a silent no-op — Hassette checks the job's internal state at entry and returns immediately if it has already been dequeued. The null-reference pattern above is still recommended when you need to reason locally about whether your code path has already cancelled the job.

### Automatic Cleanup

Hassette automatically cancels **all** jobs created by an app when that app stops or reloads. You only need to manually cancel jobs if you want to stop them *while the app is running* (e.g., a one-off timeout that is no longer needed).

## Best Practices

1. **Name your jobs**: Use the `name` parameter for better logs and safe reloads.

   Names serve two purposes beyond readability. First, they appear in every log line that mentions the job — making it easy to correlate scheduler activity with a specific task. Second, names are the key used for idempotent re-registration: using `run_every(..., name="sensor_check", if_exists="skip")` ensures the same logical job is never duplicated even if the scheduling code runs more than once within the same app lifecycle.

   ```python
   --8<-- "pages/core-concepts/scheduler/snippets/scheduler_naming.py"
   ```

2. **Avoid Overlapping Jobs**: If a job takes longer than its interval, multiple instances might run concurrently. Use an `asyncio.Lock` to guard the handler body:
   ```python
   import asyncio

   class MyApp(App[AppConfig]):
       async def on_initialize(self):
           self._sync_lock = asyncio.Lock()
           self.scheduler.run_every(self.sync_data, seconds=30)

       async def sync_data(self):
           if self._sync_lock.locked():
               return  # previous run still in progress — skip this tick
           async with self._sync_lock:
               ...  # do work
   ```

## Self-Cancelling Job Pattern

A common pattern for "poll until condition met" automations is a job that cancels itself from inside the handler. Store the `ScheduledJob` reference on the app instance so the handler can reach it:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_self_cancel.py"
```

Once `cancel()` is called, the job is immediately removed from the scheduler queue. If the dispatch loop has already picked up the job for execution, it checks for dequeue after acquiring the job and skips the handler — so double-execution cannot occur. No external coordination needed.

## Troubleshooting

### Job Not Running?

1. **Check the schedule**: Did you specify the wrong time string or interval? `run_daily(at="07:00")` fires at 7 AM; `run_once(at="07:00")` fires at 7 AM today or tomorrow if 7 AM has already passed.
2. **Exception in task**: If the task raises an unhandled exception, the scheduler catches it, logs it at `ERROR` level, and continues running — the job is not removed. Look for lines like:
   ```
   ERROR hassette.core.command_executor - Job error (job_db_id=42)
   Traceback (most recent call last):
     ...
   ValueError: unexpected sensor value
   ```
   The job will keep firing on its normal schedule until you fix the underlying error or cancel the job manually.
3. **Reference Lost**: Losing the `ScheduledJob` variable doesn't stop the job (the scheduler holds a strong reference), but it prevents you from cancelling it later.

### Runs Too Often?

- Check units: `run_every(seconds=5)` is 5 seconds, not minutes. Use `run_every(minutes=5)` for a 5-minute interval.
- Check cron expressions: `run_cron("5 * * * *")` is "at minute 5 of every hour", not "every 5 minutes". Use `run_cron("*/5 * * * *")` for every-5-minutes.

## Error Handling

When a scheduled job raises an exception, Hassette logs the error and records it for telemetry. The job continues to run on its normal schedule — it is not cancelled. You can also register an error handler to receive a typed [`SchedulerErrorContext`][hassette.scheduler.error_context.SchedulerErrorContext] with full exception details.

There are two levels of error handlers:

- **App-level**: `scheduler.on_error(handler)` — applies to all jobs on this scheduler that don't have a per-registration handler.
- **Per-registration**: `on_error=` parameter on any scheduling method — takes precedence over the app-level handler.

Both levels can be sync or async.

!!! warning "Register early — the reload gap"
    The app-level handler is resolved at dispatch time, not at job registration time. To avoid a window where a job fires before `on_error()` is called, **register `on_error()` as the first statement in `on_initialize()`**.

### App-level error handler

```python
from hassette.scheduler.error_context import SchedulerErrorContext

class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Register first to avoid the reload gap
        self.scheduler.on_error(self.on_job_error)

        self.scheduler.run_every(self.check_sensors, minutes=5)

    async def on_job_error(self, ctx: SchedulerErrorContext) -> None:
        self.logger.error(
            "Job '%s' failed: %s\n%s",
            ctx.job_name,
            ctx.exception,
            ctx.traceback,
        )

    async def check_sensors(self) -> None:
        raise ValueError("sensor unavailable")
```

### Per-registration error handler

```python
from hassette.scheduler.error_context import SchedulerErrorContext

class MyApp(App[AppConfig]):
    async def on_initialize(self):
        self.scheduler.run_every(
            self.sync_data,
            minutes=10,
            on_error=self.on_sync_error,
        )

    async def on_sync_error(self, ctx: SchedulerErrorContext) -> None:
        self.logger.warning("Sync failed: %s", ctx.exception)

    async def sync_data(self) -> None:
        raise RuntimeError("sync error")
```

### What `SchedulerErrorContext` contains

| Field | Type | Description |
|-------|------|-------------|
| `exception` | `BaseException` | The raised exception |
| `traceback` | `str` | Full formatted traceback |
| `job_name` | `str` | Human-readable job identity |
| `job_group` | `str \| None` | Group name if the job was registered with `group=` |
| `args` | `tuple[Any, ...]` | Positional arguments the job was scheduled with |
| `kwargs` | `dict[str, Any]` | Keyword arguments the job was scheduled with |

!!! note "Error handler failures"
    If the error handler itself raises or times out, the failure is logged at ERROR/WARNING and counted in the executor's error handler failure counter. The original job's telemetry record is unaffected.

## See Also

- [Scheduling Methods](methods.md) - All available scheduling methods
- [Apps Lifecycle](../apps/lifecycle.md) - Initialize and shutdown jobs properly
- [App Cache](../cache/index.md) - Remember job state across restarts
