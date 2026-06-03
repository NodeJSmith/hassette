# Triggers

A trigger determines when a scheduled job fires. Each built-in scheduling method creates a trigger internally. `schedule()` accepts a trigger directly for patterns the convenience methods do not cover.

All five built-in trigger types and [`TriggerProtocol`][hassette.types.types.TriggerProtocol] are importable from `hassette.scheduler`.

## Built-in Triggers

| Trigger | Fires | One-shot |
|---|---|---|
| `After(seconds=N)` | Once, after a fixed delay | Yes |
| `Once(at="HH:MM")` | Once, at a specific wall-clock time | Yes |
| `Every(seconds=N)` | Repeatedly on a fixed interval | No |
| `Daily(at="HH:MM")` | Once per day at a wall-clock time (DST-safe) | No |
| `Cron("expr")` | On a cron schedule (5- or 6-field) | No |

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

[`TriggerProtocol`][hassette.types.types.TriggerProtocol] defines the interface for custom scheduling patterns. Any class implementing all six methods can be passed to `schedule()`.

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_class"
```

```python
--8<-- "pages/core-concepts/scheduler/snippets/scheduler_custom_trigger.py:trigger_usage"
```

### Required Methods

| Method | Signature | Returns | Description |
|---|---|---|---|
| `first_run_time` | `(current_time: ZonedDateTime)` | `ZonedDateTime` | The time for the first execution. |
| `next_run_time` | `(previous_run: ZonedDateTime, current_time: ZonedDateTime)` | `ZonedDateTime \| None` | The time for the next execution. `None` makes the trigger one-shot. |
| `trigger_label` | `()` | `str` | Short label for logs and the web UI. |
| `trigger_detail` | `()` | `str \| None` | Optional human-readable detail string. |
| `trigger_db_type` | `()` | `Literal["interval", "cron", "once", "after", "custom"]` | Canonical type string for database storage. Application triggers return `"custom"`. |
| `trigger_id` | `()` | `str` | Stable identifier for deduplication. `if_exists="skip"` and auto-generated job names both rely on this value. |

`first_run_time` receives the current time at registration. `next_run_time` receives both the previous scheduled run and the current time, allowing drift-resistant or wall-clock-aligned strategies.

A trigger that returns `None` from `next_run_time` fires once. A trigger that always returns a future time repeats indefinitely.

## See Also

- [Scheduling Methods](methods.md): `schedule()` and the convenience methods that create triggers
- [Job Management](management.md): cancelling, inspecting, and handling errors on scheduled jobs
- [Scheduler Overview](index.md): getting started with the scheduler
