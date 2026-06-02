# Apps — Task Bucket

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Run async work outside the current handler, or call blocking code without freezing the event loop.

## What was cut (and where it goes)

- **Cross-thread communication (4 methods)** — demoted to a collapsible section. `post_to_loop()`, `run_sync()`, `run_on_loop_thread()`, and `create_task_on_loop()` are advanced threading primitives most readers never need. The two common jobs (spawn a background task, offload blocking code) should dominate the page. Advanced threading is a lookup reference for the few who need it.
- **`add(task)` and `pending_tasks()`** — cut from the main outline. These are low-level internals (register an externally-created task, snapshot pending tasks for drain/test helpers). They belong in the API reference, not in a concept page. If mentioned at all, a one-line note in the shutdown section is enough.
- **`make_async_adapter()`** — demoted below spawn and run_in_thread. It is a composition utility, not a primary pattern. Most readers never accept user-provided callbacks that could be sync or async.

## Outline

### H2: (Opening — no heading)
One sentence: `self.task_bucket` runs background work and offloads blocking calls to threads. All tracked tasks are cancelled automatically on shutdown.

### H2: Spawning Background Tasks
`spawn(coro)` fires off a coroutine that runs independently of the current handler. The bucket tracks it — no need to store the handle. Returns the `asyncio.Task` for manual inspection or cancellation if needed.

Snippet: spawn a background task.

### H2: Offloading Blocking Code
`run_in_thread(fn, *args)` runs a synchronous function in a thread pool. Await the result. Use for anything that blocks: HTTP clients without async, database drivers, file I/O, CPU-bound work.

Snippet: run_in_thread with a blocking HTTP call.

### H2: Normalizing Sync/Async Callables
??? collapsible or brief section. `make_async_adapter(fn)` wraps any callable (sync or async) into a consistent async callable. Sync functions route through `run_in_thread()` automatically. Useful when the app accepts user-provided callbacks.

Snippet: make_async_adapter.

### H2: Cross-Thread Communication
??? collapsible. Four methods for advanced threading scenarios:

#### H3: Posting to the Event Loop
`post_to_loop(fn)` schedules a callable on the main event loop from any thread. Use from inside `run_in_thread()` callbacks.

#### H3: Running Async from Sync Code
`run_sync(coro)` submits a coroutine to the event loop and blocks until it completes. Takes a coroutine object, not a callable. Warning: never call from the event loop thread — it deadlocks. Designed for `run_in_thread()` callbacks or `AppSync` methods.

#### H3: Running on the Loop Thread
`run_on_loop_thread(fn)` runs a sync function on the main event loop thread (for loop-affine code).

#### H3: Creating Tasks from Any Context
`create_task_on_loop(coro)` creates a task on the loop from any context.

### H2: Shutdown
All tracked tasks are cancelled when the app shuts down. Hassette cancels every pending task, waits up to `task_cancellation_timeout_seconds` (configurable in global settings), and logs any tasks that do not respond to cancellation.

No manual cleanup needed.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `apps_task_bucket.py` | Keep | spawn and run_in_thread |
| `apps_task_bucket_advanced.py` | Keep | make_async_adapter, post_to_loop, run_sync |

## Cross-Links

- **Links to:** Apps overview, Lifecycle (shutdown order), Cache (for persisting data — task bucket is in-memory only)
- **Linked from:** Apps overview (What an App Can Do), Lifecycle
