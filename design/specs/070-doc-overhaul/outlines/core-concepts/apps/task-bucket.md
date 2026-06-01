# Apps — Task Bucket

**Status:** Exists (70 lines), good content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Spawning Background Tasks
`self.create_task()` for fire-and-forget async work.

### H2: Offloading Blocking Code
`self.run_in_executor()` for sync/blocking calls (file I/O, HTTP libraries without async).

### H2: Normalizing Sync/Async Callables
`self.normalize_callable()` for handling both sync and async handlers uniformly.

### H2: Cross-Thread Communication
#### H3: Posting to the Event Loop
`self.call_soon()` for thread-safe event loop posting.
#### H3: Running Async from Sync Code
`self.run_coroutine()` for calling async from sync contexts.

### H2: Shutdown Behavior
How pending tasks are handled during app shutdown.

## Snippet Inventory

Snippets from `apps/snippets/` that demonstrate task bucket patterns — review and assign.

## Cross-Links

- **Links to:** Apps overview, Apps lifecycle (shutdown)
- **Linked from:** Apps overview (core capabilities)
