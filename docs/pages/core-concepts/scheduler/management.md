# Job Management

When you schedule a task, you receive a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] object. You can use this to manage the job's lifecycle.

## The ScheduledJob Object

The job object contains useful metadata:

- `job.name`: The name of the job (useful for logs).
- `job.next_run`: A `ZonedDateTime` indicating when it runs next.
- `job.cancelled`: Boolean status.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_metadata.py"
```

## Cancelling Jobs

To stop a job from running, call `cancel()`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_cancel_job.py"
```

### Automatic Cleanup

Hassette automatically cancels **all** jobs created by an app when that app stops or reloads. You only need to manually cancel jobs if you want to stop them *while the app is running* (e.g., a one-off timeout that is no longer needed).

## Best Practices

1. **Name your jobs**: Use the `name` parameter for better logs.
   ```python
   --8<-- "pages/core-concepts/scheduler/snippets/scheduler_naming.py"
   ```

2. **Check References**: If a job isn't cancelling, make sure you are calling cancel on the correct instance.

3. **Avoid Overlapping Jobs**: If a job takes longer than its interval, multiple instances might run concurrently. Ensure your logic handles this safe guarding if necessary.

## Troubleshooting

### Job Not Running?

1. **Check `start` time**: Did you accidentally schedule it for the past or tomorrow?
2. **Exception in task**: If the task raises an unhandled exception, it fails silently (logged to error). Check your logs.
3. **Reference Lost**: This doesn't stop the job (the scheduler holds a strong reference), but preventing you from cancelling it.

### Runs Too Often?

- Check units: `run_every(interval=5)` is 5 seconds, not minutes.
- Check cron: `run_cron(minute=5)` is "at minute 5 of every hour", not "every 5 minutes". Use `minute="*/5"` for intervals.

## See Also

- [Scheduling Methods](methods.md) - All available scheduling methods
- [Apps Lifecycle](../apps/lifecycle.md) - Initialize and shutdown jobs properly
- [Persistent Storage](../persistent-storage.md) - Remember job state across restarts
