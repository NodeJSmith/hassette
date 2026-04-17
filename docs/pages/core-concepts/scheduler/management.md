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
| `cancelled` | `bool` | `True` once `cancel()` has been called. The scheduler skips dispatching cancelled jobs. |

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

This marks each job in the group as cancelled, removes it from the scheduler queue, and clears the group entry. No-op if the group does not exist.

### Listing Jobs

Query registered jobs with `list_jobs()`:

```python
# All jobs for this app
all_jobs = self.scheduler.list_jobs()

# Only jobs in a specific group
morning_jobs = self.scheduler.list_jobs(group="morning")
```

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

Once `cancel()` is called, the scheduler skips the next dispatch and removes the job from the queue. No external coordination needed.

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

## See Also

- [Scheduling Methods](methods.md) - All available scheduling methods
- [Apps Lifecycle](../apps/lifecycle.md) - Initialize and shutdown jobs properly
- [App Cache](../cache/index.md) - Remember job state across restarts
