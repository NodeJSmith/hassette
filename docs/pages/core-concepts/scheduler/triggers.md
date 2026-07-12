# Triggers

A trigger determines when a scheduled job fires. Each built-in scheduling method creates a trigger internally. `schedule()` accepts a trigger directly for patterns the convenience methods do not cover.

All five built-in trigger types and [`TriggerProtocol`][hassette.types.types.TriggerProtocol] are importable from `hassette.scheduler`:

```python
from hassette.scheduler import After, Once, Every, Daily, Cron, TriggerProtocol
```

## Built-in Triggers

| Trigger | Fires | One-shot |
|---|---|---|
| `After(seconds=N)` | Once, after a fixed delay | Yes |
| `Once(at="HH:MM")` | Once, at a specific wall-clock time | Yes |
| `Every(seconds=N)` | Repeatedly on a fixed interval | No |
| `Daily(at="HH:MM")` | Once per day at a wall-clock time (DST-safe) | No |
| `Cron("expr")` | On a cron schedule (5- or 6-field) | No |

`After` also accepts `minutes=` or a `whenever.TimeDelta` via `timedelta=` — `After(minutes=5)` reads better than `After(seconds=300)`. `Every` accepts an optional `start=` anchor (a `ZonedDateTime` from the [`whenever`](https://whenever.readthedocs.io/) library, which ships with Hassette): with `Every(minutes=15, start=anchor)`, runs align to the anchor's minute marks (`:00`, `:15`, `:30`, `:45`) instead of starting from registration time.

!!! warning "Wall-clock times use the process timezone"
    `Once(at="07:00")` and `Daily(at="07:00")` interpret the time in the *process* timezone. Docker containers commonly run with `TZ=UTC` while Home Assistant uses a local zone — the job then fires at 07:00 UTC with no warning. Set the `TZ` environment variable where Hassette runs — on the container (the [Docker guide](../../getting-started/docker/index.md) compose file does this), or in the host environment for non-Docker installs — so wall-clock times mean local time.

Each convenience method on the scheduler maps to one trigger:

| Method | Creates |
|---|---|
| `run_in(func, delay)` | `After(seconds=delay)` |
| `run_once(func, at)` | `Once(at=at)` |
| `run_every(func, ...)` | `Every(...)` |
| `run_daily(func, at)` | `Daily(at=at)` |
| `run_cron(func, expr)` | `Cron(expr)` |

Triggers are passed to `schedule()` when the convenience methods do not fit. See [Scheduling Methods](methods.md) for the full method reference.

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
- [Job Management](management.md): cancelling, inspecting, and handling errors on scheduled jobs
- [Scheduler Overview](index.md): getting started with the scheduler
