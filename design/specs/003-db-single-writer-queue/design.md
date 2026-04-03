# Design: Serialize Database Writes Through a Single-Writer Queue

**Date:** 2026-03-13
**Status:** archived
**Spec:** design/specs/003-db-single-writer-queue/spec.md

## Problem

Multiple concurrent coroutines write to the SQLite database simultaneously at startup, causing `sqlite3.OperationalError: cannot commit transaction - SQL statements in progress`. When the framework finishes initializing, `register_listener`, `register_job`, `_mark_orphaned_sessions`, and `_create_session` all unblock at once and race on a single shared `aiosqlite.Connection`. aiosqlite serializes individual operations through its background thread, but does not serialize *transactions* — two coroutines can both call `execute()`, then interleave their `commit()` calls, corrupting the transaction state.

There are 9 distinct write callsites across 3 files (`database_service.py`, `command_executor.py`, `core.py`). None of them hold a direct reference to the connection outside of `DatabaseService.db` — all access it via `self.hassette.database_service.db`. This makes it practical to gate all writes through a single worker without touching the public API.

## Non-Goals

- Read operations (`SELECT`, `fetchone`, `fetchall`) are not serialized through this queue.
- CommandExecutor's existing `_write_queue` batching logic is unchanged; `_persist_batch` still collects records into a batch before writing.
- No changes to the public API of `App`, `Bus`, `Scheduler`, `Api`, or `StateManager`.
- No queue depth limits or backpressure signaling to callers.
- No cross-service transactions or distributed locking.

## Architecture

### Overview

`DatabaseService` gains a single-writer worker — an asyncio task that drains an `asyncio.Queue` of pending write coroutines sequentially. Two submission methods provide the public interface:

- **`submit(coro: Coroutine) -> Any`** — places the coroutine on the queue with an `asyncio.Future`, awaits the Future, and returns the coroutine's result (or raises its exception). Used by callers that need a return value.
- **`enqueue(coro: Coroutine) -> None`** — places the coroutine on the queue with no Future and returns immediately. Used for fire-and-forget writes. Errors are logged; the worker continues.

All 9 existing write callsites migrate to one of these two methods. No code outside the worker's loop calls `db.execute()` + `db.commit()` directly.

### DatabaseService changes

**New fields:**
```python
_db_write_queue: asyncio.Queue[tuple[Coroutine[Any, Any, Any], asyncio.Future[Any] | None]]
_db_worker_task: asyncio.Task[None] | None
```

**Worker loop (`_db_write_worker`):**
```
while True:
    coro, future = await _db_write_queue.get()
    try:
        result = await coro
        if future is not None:
            future.set_result(result)
    except Exception as exc:
        if future is not None:
            future.set_exception(exc)
        else:
            log.exception("Unhandled error in enqueued DB write")
    finally:
        _db_write_queue.task_done()
```

**`submit(coro)`:**
```
future = asyncio.get_event_loop().create_future()
await _db_write_queue.put((coro, future))
return await future
```

**`enqueue(coro)`:**
```
_db_write_queue.put_nowait((coro, None))
```

**Lifecycle — start:** Worker is created in `on_initialize()` after the connection is opened and pragmas are set:
```python
self._db_write_queue = asyncio.Queue()
self._db_worker_task = asyncio.create_task(self._db_write_worker())
```

**Lifecycle — drain:** In `on_shutdown()`, before closing the connection:
```python
await self._db_write_queue.join()   # blocks until all task_done() calls complete
self._db_worker_task.cancel()
await asyncio.gather(self._db_worker_task, return_exceptions=True)
await self._db.close()
```

`queue.join()` is safe because every item placed on the queue calls `task_done()` in the worker's `finally` block — even on error. This guarantees the drain completes even when individual writes fail.

**Internal writes migrate to `_do_*` helpers:**
- `_update_heartbeat()` → calls `self.enqueue(self._do_update_heartbeat())`; `_do_update_heartbeat()` contains the `execute` + `commit` logic
- `_run_retention_cleanup()` → calls `self.enqueue(self._do_run_retention_cleanup())`

`_set_pragmas()` is exempt — it configures the connection without a transaction and runs before the worker starts.

### CommandExecutor changes

All three write methods adopt the `_do_*` helper pattern. The public signatures are unchanged:

- `register_listener(registration)` → extracts DB logic to `_do_register_listener(registration)`, which executes the `INSERT OR CONFLICT ... RETURNING id`, fetches the row ID, commits, and returns the integer ID. The public method calls `return await self.hassette.database_service.submit(self._do_register_listener(registration))`.

- `register_job(registration)` → same pattern via `_do_register_job(registration)`.

- `_persist_batch(invocations, job_executions)` → extracts the `executemany` + `commit` block to `_do_persist_batch(invocations, job_executions)`. The public method calls `await self.hassette.database_service.submit(self._do_persist_batch(invocations, job_executions))`.

`_write_queue`, `_drain_and_persist`, `_flush_queue`, and `serve()` are entirely unchanged.

### Hassette (core.py) changes

All four session write methods adopt the `_do_*` helper pattern:

- `_mark_orphaned_sessions()` → calls `await self._database_service.submit(self._do_mark_orphaned_sessions())`. Return value unused.

- `_create_session()` → calls `self._session_id = await self._database_service.submit(self._do_create_session())`. `_do_create_session()` executes the `INSERT`, returns `cursor.lastrowid`. The session ID assignment moves to the caller (`run_forever`) rather than inside the method.

- `_finalize_session()` → calls `await self._database_service.submit(self._do_finalize_session())`.

- `_on_service_crashed(event)` → calls `self._database_service.enqueue(self._do_on_service_crashed(event))`. Fire-and-forget: the crash handler does not await the DB write. Failures are logged by the worker.

### Startup sequencing (unchanged and safe)

`CommandExecutor.on_initialize()` already awaits `wait_for_ready([database_service])`, so it cannot call `submit()` until `DatabaseService` has marked itself ready. `DatabaseService` marks ready in `serve()`, which runs after `on_initialize()` completes — after the worker is started. The worker is always alive before the first `submit()` call.

### Shutdown sequencing (safe)

The critical ordering is:

1. `Hassette.before_shutdown()` → `_finalize_session()` → `submit(_do_finalize_session())` — submitted while worker is still running
2. `Hassette.on_shutdown()` shuts down children in reverse creation order. `DatabaseService` was created first (index 0), so it shuts down last.
3. `DatabaseService.on_shutdown()` → `queue.join()` drains all queued items (including `_finalize_session`) → closes connection.

Because `DatabaseService` shuts down last, the worker accepts submissions from all other shutdown callbacks and processes them before the connection closes.

## Alternatives Considered

**Thread-based queue (Home Assistant recorder pattern):** Home Assistant uses `threading.Thread` + `queue.SimpleQueue` with fire-and-forget task objects. This works for HA because it uses synchronous `sqlite3` (blocking I/O, needs a thread) and tasks don't need return values. Hassette uses `aiosqlite` (async-native) and callers like `register_listener` require return values — making the thread-based approach a poor fit. The `asyncio.Queue` + `Future` pattern stays on the event loop and supports awaitable results natively.

**Single-connection with asyncio.Lock:** Wrapping all write sequences in `asyncio.Lock` would serialize transactions without introducing a queue. Rejected because it requires every callsite to acquire/release the lock correctly — a fragile convention that could be violated. The worker pattern enforces serialization by construction: there is only one writer.

**Connection-per-writer:** Each service gets its own `aiosqlite` connection with WAL mode enabling concurrent writers. Rejected because WAL still serializes writes at the SQLite level (only one write transaction at a time), doesn't eliminate the OperationalError, and adds connection lifecycle complexity for every service.

## Open Questions

None — all design decisions resolved before planning.

## Impact

| File | Change |
|------|--------|
| `src/hassette/core/database_service.py` | Add `_db_write_queue`, `_db_worker_task`, `submit()`, `enqueue()`, `_db_write_worker()`. Extract `_update_heartbeat` and `_run_retention_cleanup` DB logic to `_do_*` helpers. Start worker in `on_initialize()`. Drain via `queue.join()` in `on_shutdown()` before closing connection. |
| `src/hassette/core/command_executor.py` | Extract `register_listener`, `register_job`, `_persist_batch` DB logic to `_do_*` helpers; each public method calls `database_service.submit()`. `_write_queue`, `_drain_and_persist`, `_flush_queue`, `serve()` unchanged. |
| `src/hassette/core/core.py` | Extract `_mark_orphaned_sessions`, `_create_session`, `_finalize_session`, `_on_service_crashed` DB logic to `_do_*` helpers. `_create_session` returns lastrowid; `run_forever` assigns `self._session_id`. `_on_service_crashed` uses `enqueue()`. |
| `tests/integration/test_database_service.py` | Add: serialization regression test (concurrent `submit` calls don't error); error propagation test (Future receives exception, worker continues); drain test (items queued before shutdown all complete). |
| `tests/integration/test_command_executor.py` | Update `register_listener` / `register_job` tests — mock needs `database_service.submit` rather than `database_service.db`. Add test: concurrent registrations at startup don't raise `OperationalError`. |
| `tests/integration/test_session_lifecycle.py` | Update session write tests if they call `_create_session` / `_finalize_session` directly — these now require a live worker or a mock `database_service.submit`. |
