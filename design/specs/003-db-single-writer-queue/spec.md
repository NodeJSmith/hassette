---
feature_number: "003"
feature_slug: "db-single-writer-queue"
status: "approved"
created: "2026-03-13T20:53:47Z"
---

# Spec: Serialize Database Writes Through a Single-Writer Queue

## Problem Statement

Multiple concurrent operations write to the database simultaneously during startup. When the framework finishes initializing, several components unblock at once and attempt to register their listeners, jobs, and sessions in overlapping sequences. At the same time, the framework itself marks orphaned sessions from previous runs. Because these writes share a single database connection, their internal sequences — open transaction, execute statement, fetch result, commit — interleave and collide, producing a runtime error that crashes the affected operations. This error is non-deterministic: it appears under concurrent load and is invisible in sequential test runs, making it hard to reproduce and dangerous to leave unfixed.

## Goals

- All database writes are serialized through a single sequential worker so that no two writes ever execute concurrently.
- Callers that need a result from their write (e.g., an inserted row ID) can await it reliably.
- Callers that do not need a result can submit work without blocking.
- Errors from individual write operations are returned to the caller rather than swallowed.
- The worker continues processing remaining queued work after any individual operation fails.
- On shutdown, all queued writes complete before the worker stops.
- The framework starts cleanly under concurrent load with no database errors.

## Non-Goals

- Read operations are not serialized through this queue. Only writes require serialization.
- This change does not alter the batching behavior of execution record writes; existing batch collection logic stays as-is.
- No changes to the public API of the framework's user-facing classes (App, Bus, Scheduler, etc.).
- No support for cross-service transactions or distributed locking.
- No queue depth limits or backpressure signaling to callers.

## User Scenarios

**Scenario 1 — Framework startup under concurrent load**
The framework finishes connecting to Home Assistant and marks several apps as ready simultaneously. Each app's listener and job registrations are submitted to the database queue as they arrive. The queue processes them one at a time in the order received. No errors occur regardless of how many registrations burst at once.

**Scenario 2 — Caller awaiting an inserted ID**
A component registers a new listener and needs the database-assigned ID to track it. It submits the insert operation and awaits the result. The ID is returned once the worker completes the write, exactly as if the caller had written directly.

**Scenario 3 — Fire-and-forget write**
The framework updates a heartbeat timestamp on a timer. It submits the write without waiting for the result. The write is queued and executed without blocking the timer or any other operation.

**Scenario 4 — Write fails**
A submitted write raises an error (e.g., a constraint violation). The caller that awaited the result receives the error and can handle it. The queue continues processing subsequent items normally.

**Scenario 5 — Shutdown with queued work**
A shutdown signal arrives while several writes are queued. The worker finishes all queued items before stopping. No queued writes are silently discarded.

## Functional Requirements

1. **Single-writer worker**: The database service runs exactly one background worker that processes queued write operations sequentially. No write executes concurrently with another.

2. **Awaitable submission**: A `submit` method accepts a write operation and returns an awaitable result. The caller receives the operation's return value (or its exception) once the worker completes it.

3. **Fire-and-forget submission**: An `enqueue` method accepts a write operation and returns immediately without waiting for the result.

4. **Error isolation**: If a write operation raises an exception, the exception is forwarded to the caller (for `submit`) or logged (for `enqueue`). In either case, the worker continues processing the next queued item.

5. **Consistent routing**: All write operations — including those initiated by the database service itself — go through `submit` or `enqueue`. No component writes directly to the database connection outside the worker.

6. **Batch write preservation**: Execution record writes that are currently collected into batches continue to be collected and submitted as a single operation per flush. The batching logic itself is unchanged.

7. **Drain-on-shutdown**: When the database service shuts down, the worker processes all items currently in the queue before stopping. Items submitted after shutdown begins are not guaranteed to execute.

8. **Startup sequencing**: The worker starts before any external caller can submit work. Callers that submit work after shutdown has begun receive a clear error.

## Edge Cases

- **Concurrent registrations at startup**: Many `submit` calls arrive simultaneously when the framework unblocks. All must complete without error, in the order received.
- **Submit after shutdown**: If a caller submits work after the service has begun shutting down, it receives an explicit error rather than silent discard.
- **Worker crashes**: If the worker task itself crashes due to a bug in the loop (not a task-level error), the failure must be detectable and logged rather than silently ignored.
- **Enqueue before worker starts**: If `enqueue` is called before the worker has started, the queued item must not be lost.
- **Caller cancellation**: If a caller that called `submit` is cancelled before the worker completes the operation, the operation itself still runs to completion. The cancelled caller receives `CancelledError`.

## Dependencies and Assumptions

- The database service is initialized and its worker is started before any other service submits writes.
- The existing database connection lifecycle (open, close) remains owned by the database service; the worker operates on the same connection.
- No external components hold a direct reference to the database connection; all access goes through the database service.
- The framework's resource lifecycle (initialize, shutdown) provides ordered startup and shutdown hooks that the worker uses to start and drain at the correct times.

## Acceptance Criteria

- [ ] Concurrent listener and job registrations at startup complete without any database errors under repeated runs.
- [ ] A caller using `submit` receives the return value of its write operation after awaiting.
- [ ] A caller using `enqueue` returns immediately; the write completes asynchronously.
- [ ] An exception raised inside a submitted write is returned to the awaiting caller; subsequent queue items continue to execute.
- [ ] An exception raised inside an enqueued write is logged and does not affect subsequent queue items.
- [ ] At shutdown, all queued writes complete before the database connection is closed.
- [ ] No write to the database connection occurs outside the worker task.
- [ ] Existing tests pass without modification.
- [ ] The framework starts cleanly under Docker with no crashes related to concurrent database writes.
