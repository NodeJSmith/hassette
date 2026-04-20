# Scheduling Methods

The scheduler provides several methods to run tasks at different times. All methods return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob].

## Primary Entry Point

### `schedule`

The primary entry point for scheduling. All convenience methods delegate here. Use it directly when working with trigger objects.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `trigger` | `TriggerProtocol` | *(required)* | A trigger object that determines the schedule. See [Trigger Types](index.md#trigger-types). |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name for bulk management. See [Job Groups](#job-groups). |
| `jitter` | `float \| None` | `None` | Optional seconds of random offset applied at enqueue time. See [Jitter](#jitter). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global `scheduler_job_timeout_seconds` default. A positive `float` overrides it. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | When `True`, timeout enforcement is disabled for this job regardless of the global default. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
from hassette.scheduler import Every, Daily, Cron

# Fixed interval
job = self.scheduler.schedule(self.check_sensors, Every(minutes=5))

# Daily at a specific time
job = self.scheduler.schedule(self.morning_routine, Daily(at="07:00"), group="morning")

# Cron expression
job = self.scheduler.schedule(self.workday_task, Cron("0 9 * * 1-5"))
```

---

## Convenience Methods

### `run_in`
Run once after a delay. Useful for timeouts or delayed actions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `delay` | `float` | *(required)* | Delay in seconds before running. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_in.py"
```

### `run_once`
Run once at a specific wall-clock time. Accepts a `"HH:MM"` string or a `ZonedDateTime`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `at` | `str \| ZonedDateTime` | *(required)* | Target time. `"HH:MM"` is interpreted as today in the system timezone; if already past, defers to tomorrow. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

!!! note "Past times defer to tomorrow"
    If the `"HH:MM"` time has already passed today, the job is deferred to tomorrow and a WARNING is logged. To fire immediately instead, use `run_in` with a short delay.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_once.py"
```

### `run_every`
Run repeatedly at a fixed interval. Specify the interval using `hours`, `minutes`, and/or `seconds` keyword arguments (they are additive).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `hours` | `float` | `0` | Hours component of the interval. |
| `minutes` | `float` | `0` | Minutes component of the interval. |
| `seconds` | `float` | `0` | Seconds component of the interval. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_every.py"
```

---

## Convenience Interval Helpers

### `run_minutely`
Run every N minutes. Shorthand for `run_every(minutes=N)`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `minutes` | `int` | `1` | Minute interval. Must be at least 1. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_minutely.py"
```

### `run_hourly`
Run every N hours. Shorthand for `run_every(hours=N)`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `hours` | `int` | `1` | Hour interval. Must be at least 1. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_hourly.py"
```

### `run_daily`
Run once per day at a fixed wall-clock time. Uses a cron-based trigger internally for DST-correct, wall-clock-aligned scheduling.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `at` | `str` | `"00:00"` | Target wall-clock time in `"HH:MM"` format. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_daily.py"
```

---

## Cron Scheduling

### `run_cron`
Run on a schedule defined by a cron expression. Accepts both 5-field (standard Unix cron: `minute hour dom month dow`) and 6-field expressions (with seconds appended as a 6th field).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `func` | callable | *(required)* | The function to run. |
| `expression` | `str` | *(required)* | A valid 5- or 6-field cron expression. |
| `name` | `str` | `""` | Optional name for the job. |
| `group` | `str \| None` | `None` | Optional group name. See [Job Groups](#job-groups). |
| `timeout` | `float \| None` | `None` | Per-job timeout in seconds. `None` uses the global default. See [Timeouts](../configuration/global.md#timeouts). |
| `timeout_disabled` | `bool` | `False` | Disable timeout enforcement for this job. |
| `if_exists` | `"error"` \| `"skip"` | `"error"` | Behavior when a job with this name already exists. See [Idempotent Registration](#idempotent-registration). |
| `args` | `tuple` \| `None` | `None` | Positional arguments passed to `func`. |
| `kwargs` | `Mapping` \| `None` | `None` | Keyword arguments passed to `func`. |

**Cron expression fields** (5-field standard):

| Position | Field | Values | Example |
|----------|-------|--------|---------|
| 1 | minute | 0-59 | `*/15` — every 15 minutes |
| 2 | hour | 0-23 | `9` — 9 AM |
| 3 | day of month | 1-31 | `1,15` — 1st and 15th |
| 4 | month | 1-12 | `6` — June |
| 5 | day of week | 0-6 (Sunday=0) | `1-5` — weekdays |

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_run_cron.py"
```

---

## Job Groups

Schedule related jobs into a named group for bulk management. Pass `group=` to any scheduling method or to `schedule()` directly.

```python
class MorningApp(App[AppConfig]):
    async def on_initialize(self):
        self.scheduler.run_daily(self.open_blinds, at="08:00", group="morning")
        self.scheduler.run_daily(self.play_music, at="08:05", group="morning")
        self.scheduler.run_daily(self.start_coffee, at="08:10", group="morning")

    async def on_vacation_start(self):
        # Cancel all morning jobs at once
        self.scheduler.cancel_group("morning")

    async def open_blinds(self): ...
    async def play_music(self): ...
    async def start_coffee(self): ...
```

| Method | Description |
|--------|-------------|
| `cancel_group(group)` | Cancel all jobs in the group. No-op if the group does not exist. |
| `list_jobs(group=group)` | Return all jobs in the group. Without `group=`, returns all jobs. |

---

## Jitter

Add random offset to a job's enqueue time with the `jitter=` parameter. This spreads out jobs that would otherwise fire at the exact same instant — useful for avoiding thundering-herd scenarios when many apps schedule work at the same wall-clock time.

```python
from hassette.scheduler.triggers import Daily

# Spread the actual fire time by up to 30 seconds
self.scheduler.schedule(self.check_sensors, Daily(at="06:00"), jitter=30)
```

Jitter is applied to the heap sort index only — the logical `next_run` timestamp remains unjittered. This means the trigger's interval grid is not affected by jitter, only the order in which co-scheduled jobs are dispatched.

---

## Idempotent Registration

Job names must be unique within each app instance. If you register a job with a name that already exists, the scheduler raises `ValueError` by default.

All scheduling methods accept an `if_exists` parameter to control this behavior:

| Value | Behavior |
|-------|----------|
| `"error"` (default) | Raise `ValueError` if a job with the same name already exists. |
| `"skip"` | Return the existing job if its configuration matches. Raises `ValueError` if a job with the same name exists but has a different configuration. Two jobs match when they have the same callable, trigger (by `trigger_id()`), group, jitter, timeout, timeout_disabled, `args`, and `kwargs`. Useful for safe re-registration in `on_initialize`. |

This is especially useful in `on_initialize`, which runs again on app reload:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py:idempotent_registration"
```

Without `if_exists="skip"`, a reload would raise `ValueError` because `sensor_check` is already registered from the previous initialization.

## Passing Arguments to Handlers

All scheduling methods accept `args` and `kwargs` to pass data to the scheduled handler at call time. This avoids capturing mutable state in closures.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_args_kwargs.py"
```

---

## Custom Triggers

You can create your own trigger by implementing the `TriggerProtocol`. This is useful for scheduling patterns not covered by the built-in triggers — for example, polling based on solar elevation.

```python
from typing import Literal
from whenever import ZonedDateTime

from hassette.scheduler import TriggerProtocol


class SolarPollTrigger:
    """Polls on a fixed interval for use with elevation-based logic in the callback."""

    def __init__(self, check_every: int = 60):
        self.check_every = check_every

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def trigger_label(self) -> str:
        return f"solar_poll (every {self.check_every}s)"

    def trigger_detail(self) -> str | None:
        return f"every {self.check_every}s"

    def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
        return "custom"

    def trigger_id(self) -> str:
        return f"solar_poll:{self.check_every}"
```

Use it with `schedule()`:

```python
self.scheduler.schedule(self.check_sun_elevation, SolarPollTrigger(check_every=30))
```

The `TriggerProtocol` requires six methods:

| Method | Returns | Description |
|--------|---------|-------------|
| `first_run_time(current_time)` | `ZonedDateTime` | When the job should first fire. |
| `next_run_time(previous_run, current_time)` | `ZonedDateTime \| None` | When to fire next. Return `None` for one-shot triggers. |
| `trigger_label()` | `str` | Short label for logs and the web UI. |
| `trigger_detail()` | `str \| None` | Optional human-readable detail string. |
| `trigger_db_type()` | `str` | Canonical type for database storage. |
| `trigger_id()` | `str` | Stable identifier for deduplication (used by `if_exists="skip"`). |

## See Also

- [Job Management](management.md) - Name, track, and cancel scheduled jobs
- [Bus](../bus/index.md) - Combine scheduled tasks with event-driven automation
- [App Cache](../cache/index.md) - Store data between scheduled runs
