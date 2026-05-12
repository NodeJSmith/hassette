---
task_id: "T03"
title: "Add QueueHandler async log dispatch with shutdown"
status: "planned"
depends_on: ["T01"]
implements: ["FR#8", "FR#9", "AC#12", "AC#13"]
---

## Summary
Move all log I/O off the event loop by inserting a QueueHandler → QueueListener pipeline. After this task, `logger.info()` on the event loop is a non-blocking enqueue. A custom QueueListener subclass with dequeue-timeout handles batch flush timing. Shutdown is integrated via `Hassette.before_shutdown()`. The LogPersistenceHandler is created here but starts inert (no DB) — T04 wires it to the database.

## Prompt
1. In `src/hassette/logging_.py`, create a custom `HassetteQueueListener(QueueListener)` that overrides `dequeue()`:
   ```python
   def dequeue(self, block):
       try:
           return self.queue.get(block=block, timeout=0.2)
       except queue.Empty:
           # Flush any partial batch in the persistence handler
           for handler in self.handlers:
               if hasattr(handler, 'flush_if_pending'):
                   handler.flush_if_pending()
           raise
   ```
   Override `_monitor()` to handle `queue.Empty` from `dequeue()` gracefully (re-enter the dequeue loop instead of stopping).

2. Create `LogPersistenceHandler(logging.Handler)` in `src/hassette/logging_.py`:
   - Holds `_db_service: DatabaseService | None = None`, `_loop: AbstractEventLoop | None = None`, `_batch: list[dict] = []`, `_dropped: int = 0`
   - `set_database(db_service, loop)` — called later by RuntimeQueryService to wire DB access
   - `emit(record)` — if level < `log_persistence_level`, skip. Otherwise append record data to `_batch`. If `len(_batch) >= 50`, call `_flush()`.
   - `flush_if_pending()` — if `_batch` is non-empty, call `_flush()`.
   - `_flush()` — if `_db_service is None` or `_loop is None`, increment `_dropped` by batch size and clear batch. Otherwise serialize batch to a list of dicts, then `self._loop.call_soon_threadsafe(lambda batch=batch: self._db_service.enqueue(telemetry_repository.insert_log_records(batch)))` — note: `telemetry_repository` is a module-level import, not an instance attribute. Clear `_batch`.
   - `close()` — call `flush_if_pending()` before closing.
   - Property `dropped_count -> int` for observability.

3. Modify `enable_logging()` to wire the QueueHandler pipeline:
   - Create a `queue.Queue(maxsize=log_queue_max)` (from config, default 2000)
   - Create a `logging.handlers.QueueHandler(q)` — attach to the `hassette` logger
   - Create three handlers for the listener:
     a. `StreamHandler(sys.stdout)` with the `ProcessorFormatter` from T01
     b. `LogPersistenceHandler()` (inert until `set_database()` called)
     c. The existing `LogCaptureHandler` (ring buffer + WS broadcast)
   - Start `HassetteQueueListener(q, stream_handler, persistence_handler, capture_handler)`
   - Store references in module-level variables so `shutdown_logging()` can access them

4. Create `shutdown_logging()` in `src/hassette/logging_.py`:
   - Stop the `HassetteQueueListener` (calls `listener.stop()` which flushes the queue)
   - This is a module-level function like `enable_logging()`

5. Add `shutdown_logging()` call in `src/hassette/core/core.py`:
   - In `Hassette.before_shutdown()` (around line 594), add `shutdown_logging()` at the beginning (before bus listener removal). Import from `hassette.logging_`.

6. Update `LogCaptureHandler` to handle the `_shutting_down` flag:
   - Add `_shutting_down: bool = False` attribute
   - In `emit()`, check `_shutting_down` before `call_soon_threadsafe` — skip broadcast if shutting down
   - `shutdown_logging()` sets `_shutting_down = True` on the capture handler before stopping the listener

7. Add `log_queue_max` config field if not already added by T01: `log_queue_max: int = Field(default=2000, ge=1)` in `HassetteConfig`.

8. Write unit tests:
   - Test that `logger.info()` completes in <1ms (enqueue only, not waiting for I/O)
   - Test that records flow through all three handlers (stream, persistence, capture)
   - Test that `shutdown_logging()` flushes all pending records
   - Test that `LogPersistenceHandler` batches at 50 records
   - Test that the dequeue-timeout triggers `flush_if_pending()` after 200ms idle
   - Test that `LogPersistenceHandler` drops records gracefully when no DB is wired

## Focus
- The `QueueHandler` at `logging.handlers.QueueHandler` accepts a `queue.Queue` (stdlib, thread-safe), NOT `asyncio.Queue`. This is intentional — the QueueListener runs in a background thread.
- `QueueListener.stop()` puts a sentinel on the queue and joins the thread. All records enqueued before the sentinel are processed. This is the flush mechanism.
- The `_monitor()` method in QueueListener is the main loop. The default implementation calls `dequeue(block=True)` — our override adds the timeout. When `dequeue()` raises `queue.Empty`, the monitor should re-enter the loop, not stop.
- `LogCaptureHandler.emit()` at `logging_.py:103-120` uses `call_soon_threadsafe`. With QueueListener, this runs in the background thread — the pattern is still correct. The `_shutting_down` guard prevents `RuntimeError` when the event loop is closing.
- `LogCaptureHandler` no longer assigns `seq` — T02's Filter assigns `record.seq` before enqueue. `LogCaptureHandler.emit()` reads `record.seq` instead of calling `next(self._seq)`. The `_seq` counter and `itertools.count(1)` are removed from `LogCaptureHandler`.
- `before_shutdown()` at `core.py:594-610` currently removes bus listeners and finalizes the session. `shutdown_logging()` should run first.

## Verify
- [ ] FR#8: A logger.info() call on the event loop completes in <1ms (measured with time.perf_counter)
- [ ] FR#9: After shutdown_logging(), all records that were enqueued appear in the handlers' output
- [ ] AC#12: Event loop is not blocked — timing confirms enqueue-only latency
- [ ] AC#13: Clean shutdown loses no records — all emitted records appear in capture handler buffer and persistence handler batch
