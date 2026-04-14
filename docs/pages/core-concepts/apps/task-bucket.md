# Task Bucket

`self.task_bucket` is each app's task manager — it tracks background work, offloads blocking calls to threads, and cleans everything up automatically when the app shuts down.

## Spawning Background Tasks

Use `spawn()` to fire off a coroutine that runs independently of the current handler. The bucket tracks the task and cancels it on shutdown — you don't need to store the handle yourself:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:spawn"
```

`spawn()` returns the `asyncio.Task` if you need to check its status or cancel it manually.

## Offloading Blocking Code

Use `run_in_thread()` to run a synchronous function in a thread pool without blocking the event loop. Await the result:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:run_in_thread"
```

Use this for anything that blocks: HTTP clients without async support, database drivers, file I/O, CPU-bound computation.

## Normalizing Sync/Async Callables

`make_async_adapter()` wraps any callable — sync or async — into a consistent async callable. Sync functions are automatically routed through `run_in_thread()`:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:make_async_adapter"
```

This is useful when your app accepts user-provided callbacks that could be either sync or async.

## Cross-Thread Communication

### Posting to the Event Loop

`post_to_loop()` schedules a callable on the main event loop from any thread. Use this when code running in `run_in_thread()` needs to trigger an async action:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:post_to_loop"
```

### Running Async from Sync Code

`run_sync()` does the inverse — it runs an async coroutine from synchronous code by submitting it to the event loop and blocking until it completes:

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket_advanced.py:run_sync"
```

!!! warning
    `run_sync()` blocks the calling thread. Never call it from the event loop thread — it will deadlock. It's designed for use inside `run_in_thread()` callbacks or `AppSync` lifecycle methods where you need to make an async API call.

## Shutdown Behavior

All tasks tracked by the bucket are cancelled when the app shuts down. Hassette:

1. Cancels every pending task
2. Waits up to `task_cancellation_timeout_seconds` (configurable in [global settings](../configuration/global.md)) for them to finish
3. Logs any tasks that don't respond to cancellation

You don't need to clean up spawned tasks manually — the bucket handles it.

## See Also

- [Apps Overview](index.md) — core capabilities and common patterns
- [Lifecycle](lifecycle.md) — when shutdown happens and in what order
- [App Cache](../cache/index.md) — for persisting data across restarts (task bucket is for in-memory work)
