# Scheduler

This page covers how to migrate AppDaemon scheduler calls to Hassette's `self.scheduler` attribute.

## Overview

AppDaemon exposes scheduler helpers as methods directly on `self`: `self.run_in(...)`, `self.run_daily(...)`. They return an opaque handle you pass to `self.cancel_timer(handle)` to cancel the job.

Hassette exposes the scheduler as a separate attribute `self.scheduler`. Methods use named parameters, and they return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] object you cancel with `.cancel()`. Handlers can be async or sync, and they don't need to follow a fixed signature.

## Callback Signatures

**AppDaemon** requires schedule callbacks to follow `def my_callback(self, **kwargs)`. The `kwargs` dictionary includes any data you passed when scheduling plus an internal `__thread_id` value. The documentation recommends not using async functions due to the threading model.

**Hassette** scheduled jobs can be any callable — async or sync, with any parameters. If you pass keyword arguments when scheduling, declare them as parameters on your handler:

```python
--8<-- "pages/migration/snippets/scheduler_hassette.py"
```

## Method Equivalents

| AppDaemon | Hassette | Hassette Notes |
|-----------|----------|----------------|
| `self.run_in(cb, 60)` | `self.scheduler.run_in(cb, delay=60)` | Delay in seconds |
| `self.run_once(cb, time(7, 30))` | `self.scheduler.run_once(cb, at="07:30")` | `"HH:MM"` string or `ZonedDateTime` |
| `self.run_every(cb, "now", 300)` | `self.scheduler.run_every(cb, seconds=300)` | Interval via `hours=`, `minutes=`, `seconds=` |
| `self.run_minutely(cb)` | `self.scheduler.run_minutely(cb)` | Every 1 minute by default |
| `self.run_hourly(cb, time(0, 30))` | `self.scheduler.run_hourly(cb)` | Every 1 hour by default |
| `self.run_daily(cb, time(7, 30))` | `self.scheduler.run_daily(cb, at="07:30")` | Wall-clock, DST-safe (cron-backed) |
| `self.cancel_timer(handle)` | `job.cancel()` | Cancel via the returned job object |

!!! note "`run_daily` is now wall-clock-aligned"
    Hassette's `run_daily` uses a cron-based trigger internally. It fires at the specified wall-clock time every day, correctly handling DST transitions. This is different from the old interval-based approach that could drift by an hour across DST boundaries.

## Side-by-Side Comparison

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/scheduler_appdaemon.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/scheduler_hassette.py"
    ```

## Migration Example

The following shows a typical AppDaemon pattern converted to Hassette:

=== "AppDaemon"

    ```python
    from datetime import time

    def initialize(self):
        self.run_in(self.delayed_task, 60)
        self.run_daily(self.morning_task, time(7, 30))
        handle = self.run_every(self.periodic_task, "now", 300)
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/scheduler_migration.py"
    ```

**Key changes:**

- Access via `self.scheduler` instead of calling directly on `self`
- `run_daily` takes an `at="HH:MM"` string instead of a `time` object or `start=` parameter
- `run_every` takes `hours=`, `minutes=`, `seconds=` keyword arguments instead of a positional `interval`
- `run_cron` takes a cron expression string instead of keyword fields (`hour=`, `minute=`, etc.)
- Jobs return rich `ScheduledJob` objects instead of opaque handles
- Cancel with `job.cancel()` instead of `self.cancel_timer(handle)`

## Blocking Work in Scheduler Callbacks

In AppDaemon, every callback runs in its own thread, so you can do blocking IO safely. In Hassette, the scheduler automatically runs sync callables in a thread pool, regardless of whether you're using `App` or `AppSync`. This means:

- Write the callback as a plain (non-async) `def` — the scheduler detects that it's not a coroutine and runs it in a thread automatically.
- Use `AppSync` only if you also want sync lifecycle hooks (`on_initialize_sync`, `on_shutdown_sync`, etc.) — not because you need scheduler callbacks to run in threads.

If your callback is `async def`, it runs in the event loop directly. For blocking IO inside an async callback, use `asyncio.to_thread()` or `self.task_bucket.run_in_thread()`.

## See Also

- [Scheduler Overview](../core-concepts/scheduler/index.md) — the full scheduler API
- [Scheduling Methods](../core-concepts/scheduler/methods.md) — all scheduling helpers with examples
- [Job Management](../core-concepts/scheduler/management.md) — inspecting and canceling jobs
