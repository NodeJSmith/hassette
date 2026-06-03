# `Scheduler`

The scheduler runs functions after a delay, at a specific time, or on a repeating interval. `self.scheduler` is available on every [App](../apps/index.md) instance. Hassette creates it at startup and runs all jobs in the async event loop. Sync callables are wrapped automatically.

## Common Patterns

### Run after a delay

`run_in` schedules a one-shot job that fires after a fixed number of seconds.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

The `delay` parameter accepts seconds as a `float`. The job fires once and does not repeat.

### Run on a repeating interval

`run_every` schedules a job that fires repeatedly on a fixed interval.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

`seconds`, `minutes`, and `hours` are all accepted. The scheduler is drift-resistant. Each run fires relative to the previous scheduled time, not the previous actual time.

### Run daily at a fixed time

`run_daily` schedules a job that fires once per day at a wall-clock time.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

The `at` parameter accepts `"HH:MM"` strings. `run_daily` is DST-safe. It uses a cron expression internally and fires at the local wall-clock time regardless of clock changes.

## Trigger Types

Each convenience method creates a trigger object under the hood. `schedule()` accepts a trigger directly for cases not covered by the convenience methods.

| Trigger | Description | One-shot |
|---|---|---|
| `After(seconds=N)` | Fixed delay from now | Yes |
| `Once(at="HH:MM")` | Specific wall-clock time (today, or tomorrow if past) | Yes |
| `Every(seconds=N)` | Fixed recurring interval | No |
| `Daily(at="HH:MM")` | Once per day at a wall-clock time | No |
| `Cron("expr")` | Arbitrary cron expression (5- or 6-field) | No |

`hassette.scheduler` exports all five trigger types.

## Next Steps

- [Scheduling Methods](methods.md): full method reference, cron expressions, custom triggers, and per-job options including `group`, `jitter`, and `if_exists`
- [Job Management](management.md): cancelling, grouping, error handling, and the [`ScheduledJob`][hassette.scheduler.classes.`ScheduledJob`] object
