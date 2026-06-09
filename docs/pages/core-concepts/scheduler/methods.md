# Scheduling Methods

The scheduler runs handlers at times defined by trigger objects. The convenience methods below cover the common cases so most apps never need to construct a trigger directly. Every method is `async`, requires `await`, and returns a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob].

## Which method should I use?

| Timing need | Method |
|---|---|
| Run once, N seconds from now | `run_in` |
| Repeat on a fixed interval | `run_every` (or `run_minutely` / `run_hourly`) |
| Run at the same time every day | `run_daily` |
| Run on a complex or calendar schedule | `run_cron` |
| Run once at a specific wall-clock time | `run_once` |
| Use a custom trigger | `schedule` |

## Run once after a delay: `run_in`

The handler runs once after a fixed delay. The underlying [`After`][hassette.scheduler.triggers.After] trigger fires once and does not repeat.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `delay` | `float` | *(required)* | Seconds to wait before running. |

Shared parameters apply (see [Parameters every method accepts](#parameters-every-method-accepts)).

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

## Repeat on an interval: `run_every`

The handler runs repeatedly at a fixed interval. The `hours`, `minutes`, and `seconds` parameters are additive; at least one must be nonzero. Each next run is calculated from the previous run time, not from wall-clock time. The interval stays drift-resistant under load.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `hours` | `float` | `0` | Hours component of the interval. |
| `minutes` | `float` | `0` | Minutes component of the interval. |
| `seconds` | `float` | `0` | Seconds component of the interval. |

Shared parameters apply.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

### Shorthands: `run_minutely` and `run_hourly`

`run_minutely` and `run_hourly` are shorthands for `run_every` with a single integer interval parameter. Both enforce a minimum of 1.

| Method | Shorthand for | Interval parameter | Minimum |
|---|---|---|---|
| `run_minutely(func, minutes=1)` | `run_every(minutes=N)` | `minutes: int` | 1 |
| `run_hourly(func, hours=1)` | `run_every(hours=N)` | `hours: int` | 1 |

Shared parameters apply to both.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_minutely.py"
```

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_hourly.py"
```

## Run at the same time every day: `run_daily`

The handler runs once per day at a fixed wall-clock time. A cron-based trigger ensures DST-correct, wall-clock-aligned scheduling. Interval-based daily scheduling drifts by one hour on DST transitions; `run_daily` does not.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `at` | `str` | `"00:00"` | Wall-clock time in `"HH:MM"` format. |

Shared parameters apply.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

## Run on a cron schedule: `run_cron`

The handler runs on a schedule defined by a cron expression. Both 5-field (standard Unix cron) and 6-field expressions are accepted. An invalid expression raises `ValueError` at registration time.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `expression` | `str` | *(required)* | A 5- or 6-field cron expression. |

Shared parameters apply.

**Cron field reference** (5-field standard: `minute hour dom month dow`):

| Position | Field | Range | Example |
|---|---|---|---|
| 1 | minute | 0–59 | `*/15` (every 15 minutes) |
| 2 | hour | 0–23 | `9` (9 AM) |
| 3 | day of month | 1–31 | `1,15` (1st and 15th) |
| 4 | month | 1–12 | `6` (June) |
| 5 | day of week | 0–6 (Sunday=0) | `1-5` (weekdays) |

6-field expressions append seconds as a 6th field per the croniter library convention: `minute hour dom month dow second`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_cron.py"
```

## Run once at a specific time: `run_once`

The handler runs once at a specific wall-clock time. The [`Once`][hassette.scheduler.triggers.Once] trigger fires once and does not repeat.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `at` | `str \| ZonedDateTime` | *(required)* | Target time. A `"HH:MM"` string is interpreted as today in the system timezone. A [`ZonedDateTime`](https://whenever.readthedocs.io/) (from the `whenever` library — `from whenever import ZonedDateTime`) fires at the exact instant specified. |
| `if_past` | `"tomorrow"` \| `"error"` | `"tomorrow"` | Behavior when a `"HH:MM"` target has already passed today. `"tomorrow"` defers by one day and logs a WARNING. `"error"` raises `ValueError` instead. Has no effect on `ZonedDateTime` inputs. |

Shared parameters apply.

!!! note "Past `ZonedDateTime` inputs fire immediately"
    When `at` is a `ZonedDateTime` in the past, the job fires at the next scheduler tick regardless of `if_past`. Only `"HH:MM"` strings are affected by `if_past`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_once.py"
```

## Use a custom trigger: `schedule`

`schedule` is the base method all convenience methods delegate to. Most apps never call it directly. `schedule` is the right choice when a built-in convenience method cannot express the required timing, such as a custom trigger that implements [`TriggerProtocol`][hassette.types.types.TriggerProtocol]. See [Triggers](triggers.md) for the built-in trigger types and the protocol definition.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `trigger` | `TriggerProtocol` | *(required)* | A trigger object that determines first run time and recurrences. |

Shared parameters apply.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_schedule_examples.py"
```

## Parameters every method accepts

These parameters are accepted by every scheduling method. Individual method tables list only method-specific parameters.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | `""` | Identifies the job in logs and the monitoring UI. Auto-generated from the callable and trigger when empty. Must be unique within the app instance — see [Idempotent Registration](#idempotent-registration). |
| `group` | `str \| None` | `None` | Group name for bulk management. See [Job Management](management.md) for grouping. |
| `jitter` | `float \| None` | `None` | Random offset in seconds applied at enqueue time. See [Job Management](management.md) for jitter. |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` inherits the global `scheduler_job_timeout_seconds` from [`hassette.toml`](../configuration/index.md). |
| `timeout_disabled` | `bool` | `False` | Disables timeout enforcement for this job, regardless of the global default. |
| `on_error` | `SchedulerErrorHandlerType \| None` | `None` | Per-job error handler. Overrides the app-level handler set via `scheduler.on_error()`. Invoked on any exception except `CancelledError`. |
| `if_exists` | `"error"` \| `"skip"` \| `"replace"` | `"error"` | Behavior when a job with the same name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple \| None` | `None` | Positional arguments passed to the handler at call time. |
| `kwargs` | `Mapping \| None` | `None` | Keyword arguments passed to the handler at call time. |

## Passing arguments to handlers

All scheduling methods accept `args` and `kwargs` to supply data to the handler at call time. This avoids capturing mutable state in closures.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_args_kwargs.py"
```

## Idempotent registration

Job names must be unique within an app instance. Registering a second job with an existing name raises `ValueError` by default. The `if_exists` parameter controls this behavior.

| Value | Behavior |
|---|---|
| `"error"` (default) | Raises `ValueError` when a job with the same name already exists. |
| `"skip"` | Returns the existing job when its configuration matches the new registration. Raises `ValueError` when names match but configurations differ. Two jobs match when they share the same callable, trigger (by `trigger_id()`), group, jitter, timeout, `timeout_disabled`, `args`, and `kwargs`. |
| `"replace"` | Cancels the existing job and registers the new one. The new job's configuration does not need to match the old one. |

`if_exists` matters most in `on_initialize`, which re-runs on app reload (triggered by config changes or `hassette reload`).

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:idempotent_registration"
```

`"skip"` works when the job configuration is stable across reloads. `"replace"` is the right choice when the handler, trigger, or arguments may change between reloads.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:replace_registration"
```

## See Also

- [Triggers](triggers.md): built-in trigger types, `TriggerProtocol`, and writing custom triggers
- [Job Management](management.md): cancelling, inspecting, grouping, jitter, and error handling for scheduled jobs
- [Scheduler Overview](index.md): getting started with the scheduler
