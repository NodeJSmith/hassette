# Apps — Task Bucket

**Status:** Exists (70 lines), good content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Spawning Background Tasks
`self.task_bucket.spawn()` for fire-and-forget async work.

### H2: Offloading Blocking Code
`self.task_bucket.run_in_thread()` for sync/blocking calls (file I/O, HTTP libraries without async).

### H2: Adapting Sync Callables to Async
`self.task_bucket.make_async_adapter()` for wrapping sync handlers so they run in the executor automatically.

### H2: Cross-Thread Communication
#### H3: Posting to the Event Loop
`self.task_bucket.post_to_loop()` for thread-safe event loop posting.
#### H3: Running Async from Sync Code
`self.task_bucket.run_sync()` — takes a coroutine object, not a callable. Raises `RuntimeError` if called from within a running event loop.
#### H3: Running on the Loop Thread
`self.task_bucket.run_on_loop_thread()` — runs a sync function on the main event loop thread (for loop-affine code).
#### H3: Creating Tasks from Any Context
`self.task_bucket.create_task_on_loop()` — creates a task on the loop from any context.

### H2: Task Lifecycle
#### H3: `add(task)` — register an externally-created `asyncio.Task`
#### H3: `pending_tasks()` — snapshot of non-completed tasks (for drain/test helpers)

### H2: Shutdown Behavior
How pending tasks are handled during app shutdown.

## Snippet Inventory

Snippets from `apps/snippets/` that demonstrate task bucket patterns — review and assign.

## Cross-Links

- **Links to:** Apps overview, Apps lifecycle (shutdown)
- **Linked from:** Apps overview (core capabilities)
