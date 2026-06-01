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
`self.task_bucket.run_sync()` for calling async from sync contexts.

### H2: Shutdown Behavior
How pending tasks are handled during app shutdown.

## Snippet Inventory

Snippets from `apps/snippets/` that demonstrate task bucket patterns — review and assign.

## Cross-Links

- **Links to:** Apps overview, Apps lifecycle (shutdown)
- **Linked from:** Apps overview (core capabilities)
