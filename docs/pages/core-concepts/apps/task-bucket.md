# Task Bucket

`self.task_bucket` is available on every [`App`](../apps/index.md) instance. It runs background work and offloads blocking calls to threads. Handlers run on Hassette's event loop ([Async Basics](../../migration/async-basics.md) covers the event loop model), so anything slow that cannot be awaited — an HTTP library without async support, file I/O, heavy computation — goes through the task bucket instead of blocking every other handler. The bucket tracks all spawned tasks and cancels them on shutdown; no manual cleanup is required.

## Spawning Background Tasks

`self.task_bucket.spawn(coro, *, name=None)` creates a tracked background task from a coroutine — an `async def` method *called with parentheses* but not awaited. `self.poll_sensor()` creates the coroutine; `spawn` schedules it to run. The task bucket owns the task's lifecycle. The returned `asyncio.Task` can be stored for inspection or cancellation; most apps ignore it.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:spawn"
```

The spawned method is an ordinary `async def` loop:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:poll"
```

The polling loop runs indefinitely without blocking the handler that started it. On shutdown, the bucket cancels it.

## Offloading Blocking Code

A blocking call made directly in a handler — `requests.get(...)`, a database driver, heavy file I/O — freezes every other handler until it finishes. `run_in_thread(fn, *args, **kwargs)` moves the call to a thread pool so the event loop keeps running. Awaiting it pauses only the calling handler: `await` waits for the thread to finish and returns the function's result.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:run_in_thread"
```

`run_in_thread` suits HTTP clients without async support, database drivers, file I/O, and CPU-bound computation.

## Normalizing Sync/Async Callables

??? note "Advanced: make_async_adapter"

    `make_async_adapter(fn)` wraps any callable, sync or async, into a consistent async callable. Sync functions route through `run_in_thread()` automatically.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:make_async_adapter"
    ```

    Apps that wrap third-party integrations often receive callables of unknown type — a config-provided callback or a library hook that may or may not be async. The adapter normalizes them into one interface.

## Cross-Thread Communication

??? note "Advanced: cross-thread primitives"

    Four methods handle the narrow case where code in one thread needs to reach into another. Apps that only use `spawn()` and `run_in_thread()` never need these.

    ### Posting to the Event Loop

    `post_to_loop(fn, *args, **kwargs)` schedules a callable on the main event loop from any thread. The call is non-blocking. It queues the work and returns immediately.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:post_to_loop"
    ```

    ### Running Async from Sync Code

    `run_sync(fn)` submits a coroutine to the event loop and blocks the calling thread until it completes. It accepts a coroutine object, not a callable — `run_sync(self.api.get_state("sensor.x"))` works because the call expression creates the coroutine that `run_sync` then executes.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:run_sync"
    ```

    !!! warning
        `run_sync()` is safe only inside `run_in_thread()` callbacks and [`AppSync`][hassette.app.app.AppSync] lifecycle methods. Calling it from a regular `async` handler (the event loop thread) raises `RuntimeError` — `await` the async method directly there instead.

    !!! note "Entity domain actions: use `entity.sync.<method>()` instead"
        Entity objects from `self.api.sync.get_entity(...)` expose their own sync facade.
        Given `cover = self.api.sync.get_entity("cover.living_room", entities.CoverEntity)`,
        the calls `cover.sync.open_cover()` and `cover.sync.set_cover_position(position=60)`
        run synchronously without `run_sync`. Use `run_sync` for arbitrary coroutines (API calls, template
        rendering, history lookups); use `entity.sync.<method>()` for domain entity
        actions. See [API Methods](../api/methods.md#entity-sync-facades-appsync-only)
        for the full facade reference.

    ### Running on the Loop Thread

    `run_on_loop_thread(fn, *args, **kwargs)` runs a synchronous function on the main event loop thread. Loop-affine code that must not run in a worker thread belongs here.

    ### Creating Tasks from Any Context

    `create_task_on_loop(coro, *, name=None)` creates a task on the event loop from any thread context. The bucket tracks it like any other spawned task.

## Shutdown

The bucket cancels all tracked tasks when the app shuts down. Hassette cancels every pending task, waits up to `task_cancellation_timeout_seconds` (default: 5s, configurable in [global settings](../configuration/index.md)) for them to finish, and logs warnings for any tasks that do not exit within the timeout.

Manual cleanup is not required.

## Inspecting and Cancelling Tasks

Apps rarely need these directly — shutdown calls them automatically. `pending_tasks()` returns the set of tasks the bucket currently tracks. `cancel_all()` cancels every tracked task and awaits their completion; `cancel_all_sync()` is the fire-and-forget variant for sync contexts. Custom teardown sequences and the [test harness](../../testing/harness.md) drain helpers use them.

??? note "Advanced: collecting task exceptions in test infrastructure"
    `install_exception_recorder(fn)` registers a callback that receives every exception raised by a bucket task; `uninstall_exception_recorder()` removes it. The [test harness](../../testing/harness.md) uses this to surface handler failures as `DrainError`. Custom harnesses can do the same.

## See Also

- [Apps Overview](index.md) for core capabilities and common patterns
- [Lifecycle](lifecycle.md) for when shutdown happens and in what order
- [App Cache](../cache/index.md) for persisting data across restarts (the task bucket is for in-memory work only)
