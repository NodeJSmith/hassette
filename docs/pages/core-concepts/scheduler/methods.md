# Scheduling Methods

All scheduling methods return a [`ScheduledJob`][hassette.scheduler.classes.`ScheduledJob`]. Every method is `async` and requires `await`.

## Shared Parameters

These parameters are accepted by every scheduling method. Individual method tables list only method-specific parameters; shared parameters always apply.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | `""` | Name for the job. Auto-generated from the callable and trigger when empty. Must be unique within the app instance. |
| `group` | `str \| None` | `None` | Group name for bulk management. See [Job Groups](#job-groups). |
| `jitter` | `float \| None` | `None` | Random offset in seconds applied at enqueue time. See [Jitter](#jitter). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` inherits the global `scheduler_job_timeout_seconds` setting. |
| `timeout_disabled` | `bool` | `False` | Disables timeout enforcement for this job, regardless of the global default. |
| `on_error` | `SchedulerErrorHandlerType \| None` | `None` | Per-job error handler. Overrides the app-level handler set via `scheduler.on_error()`. Invoked on any exception except `CancelledError`. |
| `if_exists` | `"error"` \| `"skip"` \| `"replace"` | `"error"` | Behavior when a job with the same name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple \| None` | `None` | Positional arguments passed to the handler at call time. |
| `kwargs` | `Mapping \| None` | `None` | Keyword arguments passed to the handler at call time. |

## `schedule(func, trigger)`

The primary scheduling entry point. All convenience methods delegate here. `schedule()` accepts any object implementing [`TriggerProtocol`][hassette.types.types.TriggerProtocol], including the built-in trigger classes and custom implementations.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `trigger` | `TriggerProtocol` | *(required)* | A trigger object that determines first run time and recurrences. |

Shared parameters apply ([see above](#shared-parameters)).

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_schedule_examples.py"
```

## Delay and One-Shot Methods

### `run_in(func, delay)`

The handler runs once after a fixed delay. The [`After`][hassette.scheduler.triggers.After] trigger fires once and does not repeat.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `delay` | `float` | *(required)* | Seconds to wait before running. |

Shared parameters apply.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

### `run_once(func, at)`

The handler runs once at a specific wall-clock time. The [`Once`][hassette.scheduler.triggers.Once] trigger fires once and does not repeat.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `at` | `str \| ZonedDateTime` | *(required)* | Target time. A `"HH:MM"` string is interpreted as today in the system timezone. A `ZonedDateTime` fires at the exact instant specified. |
| `if_past` | `"tomorrow"` \| `"error"` | `"tomorrow"` | Behavior when a `"HH:MM"` target has already passed today. `"tomorrow"` defers by one day and logs a WARNING. `"error"` raises `ValueError` instead. Has no effect on `ZonedDateTime` inputs. |

Shared parameters apply.

!!! note "Past `ZonedDateTime` inputs fire immediately"
    When `at` is a `ZonedDateTime` in the past, the job fires at the next scheduler tick regardless of `if_past`. Only `"HH:MM"` strings are affected by `if_past`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_once.py"
```

## Repeating Methods

### `run_every(func, hours, minutes, seconds)`

The handler runs repeatedly at a fixed interval. The `hours`, `minutes`, and `seconds` parameters are additive; at least one must be nonzero. The interval is drift-resistant: each next run is calculated from the previous run time, not from wall-clock time.

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

### `run_minutely` / `run_hourly`

`run_minutely` and `run_hourly` are shorthands for `run_every`. They accept a single integer interval parameter and enforce a minimum of 1.

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

### `run_daily(func, at)`

The handler runs once per day at a fixed wall-clock time. A cron-based trigger ensures DST-correct, wall-clock-aligned scheduling. Interval-based daily scheduling drifts by one hour on DST transitions; `run_daily` does not.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `func` | callable | *(required)* | The handler to run. |
| `at` | `str` | `"00:00"` | Wall-clock time in `"HH:MM"` format. |

Shared parameters apply.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

### `run_cron(func, expression)`

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

6-field expressions append seconds as a 6th field per the croniter convention: `minute hour dom month dow second`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_cron.py"
```

## Job Groups

The `group=` parameter assigns a job to a named group. Groups support bulk cancellation and inspection.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_job_groups.py"
```

| Method | Description |
|---|---|
| `scheduler.cancel_group(group)` | Cancels all jobs in the group. No-op when the group does not exist. |
| `scheduler.list_jobs(group=group)` | Returns all jobs in the group. Without `group=`, returns all jobs for the app instance. |

## Jitter

The `jitter=` parameter adds a random offset to a job's dispatch time. The offset is drawn uniformly from `[0, jitter]` seconds and applied at enqueue time.

Jitter affects dispatch order within the heap. The logical `next_run` timestamp on the job remains unchanged, and the trigger's interval grid is not affected.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_jitter.py:jitter"
```

Jitter is useful when several apps schedule work at the same wall-clock time and concurrent execution would cause contention.

## Idempotent Registration

Job names must be unique within an app instance. Registering a second job with an existing name raises `ValueError` by default. The `if_exists` parameter controls this behavior.

| Value | Behavior |
|---|---|
| `"error"` (default) | Raises `ValueError` when a job with the same name already exists. |
| `"skip"` | Returns the existing job when its configuration matches the new registration. Raises `ValueError` when names match but configurations differ. Two jobs match when they share the same callable, trigger (by `trigger_id()`), group, jitter, timeout, `timeout_disabled`, `args`, and `kwargs`. |
| `"replace"` | Cancels the existing job and registers the new one. The new job's configuration does not need to match the old one. |

`if_exists` is essential in `on_initialize`, which re-runs on app reload.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:idempotent_registration"
```

`"skip"` works when the job configuration is stable across reloads. `"replace"` is the right choice when the handler, trigger, or arguments may change between reloads.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:replace_registration"
```

## Passing Arguments to Handlers

All scheduling methods accept `args` and `kwargs` to supply data to the handler at call time. This avoids capturing mutable state in closures.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_args_kwargs.py"
```

## Synchronous Scheduling

`self.scheduler.sync` exposes a `SchedulerSyncFacade` that mirrors all scheduling methods as blocking calls. This is intended for use in [`AppSync`][hassette.app.app.`AppSync`] lifecycle hooks, which run in a synchronous context.

All method signatures and parameters are identical to the async versions. The facade blocks until the registration completes.

## Custom Triggers

`TriggerProtocol` defines the interface for custom scheduling patterns. Any class implementing all six methods can be passed to `schedule()`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_class"
```

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_usage"
```

`TriggerProtocol` requires six methods:

| Method | Signature | Returns | Description |
|---|---|---|---|
| `first_run_time` | `(current_time: ZonedDateTime)` | `ZonedDateTime` | The time for the first execution. |
| `next_run_time` | `(previous_run: ZonedDateTime, current_time: ZonedDateTime)` | `ZonedDateTime \| None` | The time for the next execution. `None` makes the trigger one-shot. |
| `trigger_label` | `()` | `str` | Short label used in logs and the web UI. |
| `trigger_detail` | `()` | `str \| None` | Optional human-readable detail string. |
| `trigger_db_type` | `()` | `Literal["interval", "cron", "once", "after", "custom"]` | Canonical type string for database storage. Application triggers return `"custom"`. |
| `trigger_id` | `()` | `str` | Stable identifier for deduplication. Used by `if_exists="skip"` and auto-generated job names. |

## See Also

- [Job Management](management.md): cancelling, inspecting, and handling errors on scheduled jobs
- [`Scheduler` Overview](index.md): trigger types and the scheduling model
