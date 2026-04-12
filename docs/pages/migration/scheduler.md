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

| AppDaemon | Hassette | Notes |
|-----------|----------|-------|
| `self.run_in(cb, 60)` | `self.scheduler.run_in(cb, delay=60)` | Delay in seconds |
| `self.run_once(cb, time(7, 30))` | `self.scheduler.run_once(cb, start=time(7, 30))` | Runs once at given time |
| `self.run_every(cb, "now", 300)` | `self.scheduler.run_every(cb, start=self.now(), interval=300)` | Repeating interval in seconds |
| `self.run_minutely(cb)` | `self.scheduler.run_minutely(cb)` | Every minute |
| `self.run_hourly(cb, time(0, 30))` | `self.scheduler.run_hourly(cb, start=time(0, 30))` | Every hour at given offset |
| `self.run_daily(cb, time(7, 30))` | `self.scheduler.run_daily(cb, start=time(7, 30))` | Every day at given time |
| `self.cancel_timer(handle)` | `job.cancel()` | Cancel via the returned job object |

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

In AppDaemon, every callback runs in its own thread, so you can do blocking IO safely. In Hassette, callbacks run in the asyncio event loop. If your callback does blocking IO (file reads, database calls, slow HTTP requests), either:

1. Use `AppSync` and write a synchronous callback — it runs in a thread automatically
2. Make the callback `async def` and use `asyncio.to_thread()` or `self.task_bucket.run_in_thread()` for the blocking part

## Further Reading

- [Scheduler Overview](../core-concepts/scheduler/index.md) — the full scheduler API
- [Scheduling Methods](../core-concepts/scheduler/methods.md) — all scheduling helpers with examples
- [Job Management](../core-concepts/scheduler/management.md) — inspecting and canceling jobs
