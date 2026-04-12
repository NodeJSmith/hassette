# Scheduling Methods

The scheduler provides several helper methods to run tasks at different times. All methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob].

## Standard Helpers

### `run_in`
Run once after a delay. Useful for timeouts or delayed actions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `delay` | `TimeDelta` \| `float` | *(required)* | Delay before running. Floats are treated as seconds. |
| `name` | `str` | `""` | Optional name for the job. |
| `start` | `ScheduleStartType` | `None` | If provided, overrides the delay and runs at this exact time. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

### `run_once`
Run once at a specific time.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `start` | `ScheduleStartType` | *(required)* | When to run. Accepts a `ZonedDateTime`, `datetime.time`, `(hour, minute)` tuple, or a numeric seconds offset. See [The `start` Parameter](index.md#the-start-parameter). |
| `name` | `str` | `""` | Optional name for the job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_once.py"
```

### `run_every`
Run repeatedly at a fixed interval.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `interval` | `TimeDelta` \| `float` | *(required)* | Interval between runs. Floats are treated as seconds. |
| `name` | `str` | `""` | Optional name for the job. |
| `start` | `ScheduleStartType` | `None` | First-run time. If `None`, first run is at now + interval. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

---

## Convenience Helpers

### `run_minutely`
Run every N minutes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `minutes` | `int` | `1` | Minute interval. Must be at least 1. |
| `name` | `str` | `""` | Optional name for the job. |
| `start` | `ScheduleStartType` | `None` | First-run time. If `None`, runs at now + N minutes. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_minutely.py"
```

### `run_hourly`
Run every N hours.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `hours` | `int` | `1` | Hour interval. Must be at least 1. |
| `name` | `str` | `""` | Optional name for the job. |
| `start` | `ScheduleStartType` | `None` | First-run time. If `None`, runs at now + N hours. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_hourly.py"
```

### `run_daily`
Run on a fixed daily interval (every N days). Use `start` to anchor the first run to a specific time; for a strict "every day at exactly 7:00 AM" schedule, use [`run_cron`](#run_cron) instead.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `days` | `int` | `1` | Number of days between runs. Must be 1–365. |
| `name` | `str` | `""` | Optional name for the job (useful for logs and cancellation). |
| `start` | `ScheduleStartType` | `None` | First-run time. If `None`, runs at now + N days. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

---

## Cron Scheduling

### `run_cron`
Run on a complex schedule using cron syntax.

**Cron fields** — each accepts an `int` (exact value) or a `str` (cron expression like `"*/5"`, `"1,3,5"`, `"1-5"`):

| Parameter      | Values         | Default | Example                                |
| -------------- | -------------- | ------- | -------------------------------------- |
| `second`       | 0-59           | `0`     | `0` - top of the minute                |
| `minute`       | 0-59           | `0`     | `"*/15"` - every 15 minutes            |
| `hour`         | 0-23           | `0`     | `14` - 2 PM                            |
| `day_of_month` | 1-31           | `"*"`   | `"1,15"` - 1st and 15th of the month   |
| `month`        | 1-12           | `"*"`   | `6` - June                             |
| `day_of_week`  | 0-6 (Sunday=0) | `"*"`   | `"1-5"` - weekdays only                |

**Common parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `name` | `str` | `""` | Optional name for the job. |
| `start` | `ScheduleStartType` | `None` | Earliest time the cron schedule may fire. See [The `start` Parameter](index.md#the-start-parameter). |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_cron.py"
```

## Idempotent Registration

Job names must be unique within each app instance. If you register a job with a name that already exists, the scheduler raises `ValueError` by default.

All `run_*` methods accept an `if_exists` parameter to control this behavior:

| Value | Behavior |
|-------|----------|
| `"error"` (default) | Raise `ValueError` if a job with the same name already exists. |
| `"skip"` | Return the existing job if its configuration matches. Raises `ValueError` if a job with the same name exists but has a different configuration (e.g., different interval or callback). Useful for safe re-registration in `on_initialize`. |

This is especially useful in `on_initialize`, which runs again on app reload:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:idempotent_registration"
```

Without `if_exists="skip"`, a reload would raise `ValueError` because `sensor_check` is already registered from the previous initialization.

## See Also

- [Job Management](management.md) - Name, track, and cancel scheduled jobs
- [Bus](../bus/index.md) - Combine scheduled tasks with event-driven automation
- [App Cache](../cache/index.md) - Store data between scheduled runs
