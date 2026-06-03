# Task Bucket

`self.task_bucket` runs background work and offloads blocking calls to threads. The bucket tracks all spawned tasks and cancels them on shutdown.

## Spawning Background Tasks

`spawn(coro, *, name=None)` creates a tracked background task from a coroutine. The bucket owns the task's lifecycle. The returned `asyncio.Task` is available for inspection or cancellation.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:spawn"
```

The polling loop runs indefinitely without blocking the handler that started it. On shutdown, the bucket cancels it.

## Offloading Blocking Code

`run_in_thread(fn, *args, **kwargs)` runs a synchronous function in a thread pool. The event loop stays unblocked while the thread works. The return value is a coroutine that resolves to the function's result.

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

    Apps that accept user-provided callbacks benefit from this. The adapter normalizes sync and async callables into one interface.

## Cross-Thread Communication

??? note "Advanced: cross-thread primitives"

    Four methods handle the narrow case where code in one thread needs to reach into another. Typical automations rarely need them.

    ### Posting to the Event Loop

    `post_to_loop(fn, *args, **kwargs)` schedules a callable on the main event loop from any thread. The call is non-blocking. It queues the work and returns immediately.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:post_to_loop"
    ```

    ### Running Async from Sync Code

    `run_sync(coro)` submits a coroutine to the event loop and blocks the calling thread until it completes. It accepts a coroutine object, not a callable.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:run_sync"
    ```

    !!! warning
        `run_sync()` blocks the calling thread. Calling it from the event loop thread causes a deadlock. It is safe inside `run_in_thread()` callbacks and `AppSync` lifecycle methods only.

    ### Running on the Loop Thread

    `run_on_loop_thread(fn, *args, **kwargs)` runs a synchronous function on the main event loop thread. Loop-affine code that must not run in a worker thread belongs here.

    ### Creating Tasks from Any Context

    `create_task_on_loop(coro, *, name=None)` creates a task on the event loop from any thread context. The bucket tracks it like any other spawned task.

## Shutdown

The bucket cancels all tracked tasks when the app shuts down. Hassette cancels every pending task, waits up to `task_cancellation_timeout_seconds` (configurable in [global settings](../configuration/index.md)) for them to finish, and logs warnings for any tasks that do not exit within the timeout.

Manual cleanup is not required.

## See Also

- [Apps Overview](index.md) for core capabilities and common patterns
- [Lifecycle](lifecycle.md) for when shutdown happens and in what order
- [App Cache](../cache/index.md) for persisting data across restarts (the task bucket is for in-memory work only)
