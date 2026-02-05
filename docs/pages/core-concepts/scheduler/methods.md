# Scheduling Methods

The scheduler provides several helper methods to run tasks at different times. All methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob].

## Standard Helpers

### `run_in`
Run once after a delay. Useful for timeouts or delayed actions.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
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

## See Also

- [Job Management](management.md) - Name, track, and cancel scheduled jobs
- [Bus](../bus/index.md) - Combine scheduled tasks with event-driven automation
- [Persistent Storage](../persistent-storage.md) - Store data between scheduled runs
