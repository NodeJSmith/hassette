# Triggers

A trigger determines when a scheduled job fires. Each built-in scheduling method creates a trigger internally. `schedule()` accepts a trigger directly for patterns the convenience methods do not cover.

All six built-in trigger types and [`TriggerProtocol`][hassette.types.types.TriggerProtocol] are importable from `hassette.scheduler`:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_trigger_imports.py"
```

## Built-in Triggers

| Trigger | Fires | One-shot |
|---|---|---|
| `After(seconds=N)` | Once, after a fixed delay | Yes |
| `Once(at="HH:MM")` | Once, at a specific wall-clock time | Yes |
| `Every(seconds=N)` | Repeatedly on a fixed interval | No |
| `Daily(at="HH:MM")` | Once per day at a wall-clock time (DST-safe) | No |
| `Cron("expr")` | On a cron schedule (5- or 6-field) | No |
| `EntityTime("sensor.x")` | At a time read from an entity, rescheduling when it changes | No |

`After` also accepts `minutes=` or a `whenever.TimeDelta` via `timedelta=` — `After(minutes=5)` reads better than `After(seconds=300)`. `Every` accepts an optional `start=` anchor (a `ZonedDateTime` from the [`whenever`](https://whenever.readthedocs.io/) library, which ships with Hassette): with `Every(minutes=15, start=anchor)`, runs align to the anchor's minute marks (`:00`, `:15`, `:30`, `:45`) instead of starting from registration time.

!!! warning "Wall-clock times use the configured timezone"
    `Once(at="07:00")` and `Daily(at="07:00")` interpret the time in the configured timezone. The [`timezone`](../configuration/index.md#timezone) field in `hassette.toml` controls which timezone the scheduler uses; when unset, the process timezone applies. Docker containers commonly default to UTC while Home Assistant uses a local zone, so the job fires at 07:00 UTC with no warning. `timezone = "America/Chicago"` in `hassette.toml` (or `HASSETTE__TIMEZONE`) resolves this. The `TZ` environment variable works as a fallback.

Each convenience method on the scheduler maps to one trigger:

| Method | Creates |
|---|---|
| `run_in(func, delay)` | `After(seconds=delay)` |
| `run_once(func, at)` | `Once(at=at)` |
| `run_every(func, ...)` | `Every(...)` |
| `run_daily(func, at)` | `Daily(at=at)` |
| `run_cron(func, expr)` | `Cron(expr)` |

Triggers are passed to `schedule()` when the convenience methods do not fit. See [Scheduling Methods](methods.md) for the full method reference.

`EntityTime` has no convenience method — it is only available through `schedule()`.

## Entity-Driven Times

`EntityTime` reads its fire time from a Home Assistant entity. The scheduler moves the job whenever that entity changes. Phone alarms, `input_datetime` helpers, and `sun.sun` attributes all name moving times. `EntityTime` follows those times without app-level remove-and-reschedule code.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_entity_time.py:alarm"
```

The job fires when `sensor.phone_next_alarm` says it should. An earlier alarm moves the job earlier.

| Parameter | Effect |
|---|---|
| `entity_id` | The entity holding the time. Required. |
| `attribute` | Read the time from this attribute instead of the entity's state. |
| `offset` | A `TimeDelta` (`from whenever import TimeDelta`) shifting the fire time. Negative values fire early. |
| `daily` | Keep only the time of day and fire at it every day. |

`offset` covers the common "before the alarm" case. `daily=True` turns one absolute moment into a recurring wall-clock schedule:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_entity_time.py:offset_daily"
```

That job fires 30 minutes before the configured routine time each day. Without `daily=True`, the trigger fires once at the entity's absolute date and time. It then waits until the entity names a new time.

`attribute=` reaches times that live outside an entity's state:

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_entity_time.py:attribute"
```

`EntityTime` parses the value shapes Home Assistant uses for times. It accepts offset-aware ISO strings, naive ISO date-times, time-only strings, and unix timestamps. Naive and time-only values are read in the configured timezone.

### When the entity has no time

An entity can be unavailable, report `unknown`, or hold a non-time value. A phone with no alarm set does exactly this. The job's `schedule_status` becomes `waiting`: it stays registered and watched by the entity-change listener, but carries no `next_run` and sits off the scheduler's due-time heap. The entity's next change puts it back on a real schedule — reactivation goes through the same watcher, so no polling or timer is involved.

[`hassette job`](../../cli/commands.md#hassette-job) and the web UI render a `waiting` job as "Waiting for entity time." instead of a next-run timestamp. A missing next run means the entity currently names no time, not that the job stopped.

!!! warning "Entity-driven times still use the configured timezone"
    A time-only or naive value uses the configured timezone, like `Daily(at="07:00")`. A container defaulting to UTC can disagree with Home Assistant's local zone. That mismatch makes jobs fire at the wrong hour.

## Custom Triggers

A custom trigger expresses a timing pattern the built-in types cannot: phase-locked schedules, adaptive intervals, or schedules driven by external state. [`TriggerProtocol`][hassette.types.types.TriggerProtocol] defines the interface. Any class implementing all six methods can be passed to `schedule()`. Inheriting `TriggerProtocol` is optional — duck typing works — but it lets Pyright catch missing methods.

Trigger methods use [`ZonedDateTime`](https://whenever.readthedocs.io/) from the `whenever` library (`from whenever import ZonedDateTime`) — Hassette's date/time type for timezone-safe scheduling.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_class"
```

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_usage"
```

### What to implement

Two methods control when the job fires. They are the load-bearing part of any custom trigger.

| Method | Signature | Returns | Description |
|---|---|---|---|
| `first_run_time` | `(current_time: ZonedDateTime)` | `ZonedDateTime` | The time for the first execution. |
| `next_run_time` | `(previous_run: ZonedDateTime, current_time: ZonedDateTime)` | `ZonedDateTime \| None` | The time for the next execution. `None` makes the trigger one-shot. |

`first_run_time` receives the current time at registration. `next_run_time` receives both the previous scheduled run and the current time, allowing drift-resistant or wall-clock-aligned strategies. A trigger that returns `None` from `next_run_time` fires once. A trigger that always returns a future time repeats indefinitely.

The remaining four methods cover display and deduplication.

| Method | Signature | Returns | Description |
|---|---|---|---|
| `trigger_label` | `()` | `str` | Short label for logs and the web UI. |
| `trigger_detail` | `()` | `str \| None` | Optional human-readable detail string. |
| `trigger_db_type` | `()` | `str` | Canonical type string for database storage. Application triggers return `"custom"`. |
| `trigger_id` | `()` | `str` | Stable identifier for deduplication, used by [`if_exists="skip"`](methods.md#idempotent-registration). |

## See Also

- [Scheduling Methods](methods.md): `schedule()` and the convenience methods that create triggers
- [Job Management](management.md): removing, inspecting, schedule status, and handling errors on live jobs
- [Scheduler Overview](index.md): getting started with the scheduler
