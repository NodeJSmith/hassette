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

!!! note "Interval-based, not cron-based"
    All Hassette interval methods (`run_minutely`, `run_hourly`, `run_daily`) are interval-based, not cron-based — they fire at the given `start` time and then every N units later, not at wall-clock boundaries. Use `run_cron` for wall-clock alignment.

| AppDaemon | Hassette | Notes |
|-----------|----------|-------|
| `self.run_in(cb, 60)` | `self.scheduler.run_in(cb, delay=60)` | Delay in seconds |
| `self.run_once(cb, time(7, 30))` | `self.scheduler.run_once(cb, start=time(7, 30))` | Runs once at given time |
| `self.run_every(cb, "now", 300)` | `self.scheduler.run_every(cb, interval=300, start=self.now())` | Repeating interval in seconds |
| `self.run_minutely(cb)` | `self.scheduler.run_minutely(cb)` | Interval-based. The first run fires within one scheduler tick (typically under 1 second) — not at the next wall-clock minute boundary. |
| `self.run_hourly(cb, time(0, 30))` | `self.scheduler.run_hourly(cb, start=time(0, 30))` | Interval-based, not cron-based. Fires at the given offset, then every N hours. |
| `self.run_daily(cb, time(7, 30))` | `self.scheduler.run_daily(cb, start=time(7, 30))` | Interval-based, not cron-based. If Hassette restarts after the start time has passed for the day, the job fires immediately at startup, then at the start time the following day. Use `run_cron` for strict wall-clock scheduling that skips a missed run rather than firing immediately. |
| `self.cancel_timer(handle)` | `job.cancel()` | Cancel via the returned job object |

!!! warning "Always pass `start=` as a keyword argument"
    Unlike AppDaemon, Hassette's `run_daily`, `run_hourly`, and `run_minutely` take a count (`days`, `hours`, `minutes`) as their second positional parameter. Passing a `time` object positionally will cause a `TypeError`. Always use the keyword form:

    ```python
    # Correct
    self.scheduler.run_daily(self.morning_task, start=time(7, 30))

    # Wrong — time(7, 30) is interpreted as the `days` argument
    self.scheduler.run_daily(self.morning_task, time(7, 30))
    ```

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

The following shows a typical AppDaemon pattern converted to Hassette. Note the named parameters and the use of `self.now()` for the `start` argument:

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
- Use named parameters (`delay=`, `start=`, `interval=`)
- Jobs return rich `ScheduledJob` objects instead of opaque handles
- Cancel with `job.cancel()` instead of `self.cancel_timer(handle)`

## Blocking Work in Scheduler Callbacks

In AppDaemon, every callback runs in its own thread, so you can do blocking IO safely. In Hassette, the scheduler automatically wraps sync callables in a thread pool via `make_async_adapter`, regardless of whether you're using `App` or `AppSync`. This means:

- Write the callback as a plain (non-async) `def` — the scheduler detects that it's not a coroutine and runs it in a thread automatically.
- Use `AppSync` only if you also want sync lifecycle hooks (`on_initialize_sync`, `on_shutdown_sync`, etc.) — not because you need scheduler callbacks to run in threads.

If your callback is `async def`, it runs in the event loop directly. For blocking IO inside an async callback, use `asyncio.to_thread()` or `self.task_bucket.run_in_thread()`.

## See Also

- [Scheduler Overview](../core-concepts/scheduler/index.md) — the full scheduler API
- [Scheduling Methods](../core-concepts/scheduler/methods.md) — all scheduling helpers with examples
- [Job Management](../core-concepts/scheduler/management.md) — inspecting and canceling jobs
