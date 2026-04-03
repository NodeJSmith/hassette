# Scheduling Methods

The scheduler provides several helper methods to run tasks at different times. All methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob].

## Standard Helpers

### `run_in`
Run once after a delay (in seconds). Useful for timeouts or delayed actions.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

### `run_once`
Run once at a specific time. Accepts an absolute datetime, a `(hour, minute)` tuple, or a time string.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_once.py"
```

### `run_every`
Run repeatedly at a fixed interval.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

---

## Convenience Helpers

### `run_minutely`
Run every N minutes.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_minutely.py"
```

### `run_hourly`
Run every N hours.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_hourly.py"
```

### `run_daily`
Run once a day at a specific time.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

---

## Cron Scheduling

### `run_cron`
Run on a complex schedule using cron syntax.

| Parameter      | Values         | Example                         |
| -------------- | -------------- | ------------------------------- |
| `second`       | 0-59           | `0` - top of the minute         |
| `minute`       | 0-59           | `30` - 30 minutes past the hour |
| `hour`         | 0-23           | `14` - 2 PM                     |
| `day_of_month` | 1-31           | `15` - 15th of the month        |
| `month`        | 1-12           | `6` - June                      |
| `day_of_week`  | 0-6 (Sunday=0) | `1` - Monday                    |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_cron.py"
```

## Idempotent Registration

Job names must be unique within each app instance. If you register a job with a name that already exists, the scheduler raises `ValueError` by default.

All `run_*` methods accept an `if_exists` parameter to control this behavior:

| Value | Behavior |
|-------|----------|
| `"error"` (default) | Raise `ValueError` if a job with the same name already exists. |
| `"skip"` | Silently return the existing job if it matches. Useful for safe re-registration. |

This is especially useful in `on_initialize`, which runs again on app reload:

```python
async def on_initialize(self):
    # Safe to call on every reload — won't create duplicates
    self.scheduler.run_every(
        self.check_sensors,
        60,
        name="sensor_check",
        if_exists="skip",
    )
```

Without `if_exists="skip"`, a reload would raise `ValueError` because `sensor_check` is already registered from the previous initialization.

## See Also

- [Job Management](management.md) - Name, track, and cancel scheduled jobs
- [Bus](../bus/index.md) - Combine scheduled tasks with event-driven automation
- [Persistent Storage](../persistent-storage.md) - Store data between scheduled runs
