# `Scheduler`

Hassette scheduling lives on `self.scheduler`. All methods are `async` and return a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] object for cancellation.

## Method Equivalents

| AppDaemon | Hassette | Notes |
|-----------|----------|-------|
| `self.run_in(cb, 60)` | `await self.scheduler.run_in(cb, delay=60)` | Delay in seconds |
| `self.run_once(cb, time(7, 30))` | `await self.scheduler.run_once(cb, at="07:30")` | `"HH:MM"` string or `ZonedDateTime` |
| `self.run_every(cb, "now", 300)` | `await self.scheduler.run_every(cb, seconds=300)` | Use `hours=`, `minutes=`, or `seconds=` |
| `self.run_minutely(cb)` | `await self.scheduler.run_minutely(cb)` | Every 1 minute |
| `self.run_hourly(cb, time(0, 30))` | `await self.scheduler.run_hourly(cb)` | Every 1 hour |
| `self.run_daily(cb, time(7, 30))` | `await self.scheduler.run_daily(cb, at="07:30")` | Wall-clock, DST-safe |
| `self.cancel_timer(handle)` | `job.cancel()` | Cancel via the returned job object |
| — | `await self.scheduler.run_cron(cb, "0 7 * * *")` | Hassette-only; cron expression |
| — | `await self.scheduler.schedule(cb, trigger)` | Hassette-only; custom trigger object |

!!! note "`run_daily` is now cron-backed"
    Hassette's `run_daily` fires at the specified wall-clock time every day, handling DST transitions correctly. An interval-based approach drifts by an hour across a DST boundary. The cron-backed implementation does not.

Every scheduling call returns a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob]. Call `.cancel()` on it to stop the job.

## Callback Signatures

AppDaemon requires all schedule callbacks to match `def my_callback(self, **kwargs)`. The `kwargs` dict carries any data you passed at registration, plus an internal `__thread_id` key.

Hassette accepts any callable, async or sync, with any parameters. Keyword arguments passed when scheduling arrive as named parameters on the handler:

```python
--8<-- "pages/migration/snippets/scheduler_hassette.py"
```

No fixed signature. No `**kwargs` unwrapping.

## Migration Example

The complete before/after for an app that uses `run_in`, `run_daily`, and `run_every`:

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/scheduler_appdaemon.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/scheduler_migration.py"
    ```

**Key changes:**

- Call scheduling methods on `self.scheduler`, not directly on `self`
- `await` every scheduling call
- `run_daily` takes `at="HH:MM"` instead of a `datetime.time` object
- `run_every` takes `hours=`, `minutes=`, or `seconds=` instead of a positional interval
- Jobs return `ScheduledJob` objects; cancel with `job.cancel()` instead of `self.cancel_timer(handle)`

## Blocking Work

In AppDaemon, every callback runs in its own thread, so blocking IO is safe anywhere.

In Hassette, sync callables passed to the scheduler run in a thread pool automatically. Write a plain `def` callback and Hassette detects it is not a coroutine. No extra configuration needed.

```python
def periodic_sync_task(self):
    # Runs in a thread pool. Blocking IO is safe here.
    data = requests.get("http://example.com/api").json()
    ...
```

Async callbacks run in the event loop directly. For blocking IO inside an `async def` callback, offload with `asyncio.to_thread()` or `self.task_bucket.run_in_thread()`:

```python
async def periodic_async_task(self):
    # Must offload blocking work explicitly
    data = await asyncio.to_thread(requests.get, "http://example.com/api")
    ...
```

[`AppSync`][hassette.app.app.AppSync] is for sync lifecycle hooks (`on_initialize_sync`, `on_shutdown_sync`). Sync scheduler callbacks already run in a thread pool regardless of base class.

## See Also

- [`Scheduler` Overview](../core-concepts/scheduler/index.md). The full scheduler API.
- [Scheduling Methods](../core-concepts/scheduler/methods.md). All helpers with examples.
- [Job Management](../core-concepts/scheduler/management.md). Inspecting and canceling jobs.
