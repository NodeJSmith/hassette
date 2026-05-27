---
task_id: "T03"
title: "Create LoggingService Resource"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#6", "AC#1", "AC#2", "AC#3", "AC#5", "AC#10"]
---

## Summary
Create the `LoggingService` Resource that owns the full async logging pipeline. This is the core of the design: a Resource with `depends_on=[DatabaseService]` that upgrades logging from sync to async during `on_initialize()`, manages the QueueListener lifecycle, and provides constructor injection for LogPersistenceHandler. The async pipeline (QueueListener + stream + capture) starts unconditionally; persistence degrades gracefully on failure.

## Prompt
1. Create `src/hassette/core/logging_service.py` with class `LoggingService(Resource)`:

   ```
   depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
   ```

   **`__init__(self, hassette, *, stream_handler, parent=None)`:**
   - Call `super().__init__(hassette, parent=parent)`
   - Store `self._stream_handler = stream_handler`
   - Create `self.capture_handler = LogCaptureHandler(buffer_size=hassette.config.web_api.log_buffer_size)`
   - Initialize `self.persistence_handler: LogPersistenceHandler | None = None`
   - Initialize `self._queue_listener: HassetteQueueListener | None = None`
   - Initialize `self._queue_handler: logging.handlers.QueueHandler | None = None`

   **`async def on_initialize(self)`:**
   - Defensive cleanup: get the `hassette` logger, remove any existing QueueHandler instances, stop any running `self._queue_listener`
   - Build handlers list: `[self._stream_handler, self.capture_handler]`
   - Try persistence (best-effort):
     ```python
     try:
         loop = asyncio.get_running_loop()
         self.persistence_handler = LogPersistenceHandler(
             self.hassette.database_service, loop,
             persistence_level=logging.getLevelNamesMapping()[self.hassette.config.logging.log_persistence_level],
         )
         handlers.append(self.persistence_handler)
     except Exception:
         self.logger.error("Failed to create persistence handler — logs will not be persisted")
         self.persistence_handler = None
     ```
   - Create bounded queue: `queue.Queue(maxsize=self.hassette.config.logging.log_queue_max)`
   - Create QueueHandler with CorrelationFilter attached
   - Create `HassetteQueueListener(q, *handlers)`
   - Atomic swap: `logger.addHandler(queue_handler)` then `logger.removeHandler(self._stream_handler)`
   - Start the QueueListener: `self._queue_listener.start()`
   - Store references: `self._queue_handler = queue_handler`
   - Call `self.mark_ready(reason="LoggingService initialized")`

   **`async def on_shutdown(self)`:**
   - Set `self.capture_handler.shutting_down = True`
   - Log warning: "LoggingService shutting down — subsequent log records will be console-only"
   - Get the `hassette` logger
   - Remove QueueHandler: `logger.removeHandler(self._queue_handler)`
   - Restore StreamHandler: `logger.addHandler(self._stream_handler)`
   - Stop QueueListener via `asyncio.to_thread()` with 5s timeout (wrap in try/except asyncio.TimeoutError, log warning on timeout)
   - Flush persistence handler: `if self.persistence_handler: self.persistence_handler.flush_if_pending()`

   **Property `@property def dropped_count(self) -> int`:**
   - Return `self.persistence_handler.dropped_count if self.persistence_handler else 0`

2. Update `LogPersistenceHandler` in `src/hassette/logging_.py`:
   - Change constructor to accept `db_service` and `loop` directly (constructor injection):
     ```python
     def __init__(self, db_service: "DatabaseService", loop: asyncio.AbstractEventLoop, persistence_level: int = logging.INFO):
     ```
   - Remove `set_database()` method entirely
   - Update `_flush()` to use `self._db_service.enqueue(self._db_service._insert_log_records(b))`
   - Remove the `_repository` attribute if not already removed in T01

3. Wire in `src/hassette/core/core.py`:
   - Add import for LoggingService
   - In `wire_services()`, after `self._database_service = self.add_child(DatabaseService)`:
     ```python
     self._logging_service = self.add_child(LoggingService, stream_handler=self._basic_stream_handler)
     ```
   - Add `_logging_service` slot declaration with the other service slots
   - Add `logging_service` property (same pattern as `database_service` property)
   - Update `get_log_records_dropped()` to use `self.logging_service.dropped_count`

4. Create unit tests in `tests/unit/core/test_logging_service.py`:
   - Test `on_initialize` creates QueueListener and starts it
   - Test `on_initialize` with persistence failure still starts the pipeline
   - Test `on_shutdown` stops listener and restores StreamHandler
   - Test `mark_ready` is called after pipeline starts
   - Test defensive cleanup removes stale handlers on re-init
   - Test sync→async swap: log before and after init, verify all records arrive

5. Run: `timeout 300 uv run pytest tests/unit/core/test_logging_service.py -v`

## Focus
- LoggingService is a **Resource**, NOT a Service. No `serve()`, no RestartSpec.
- `LogCaptureHandler` is created in `__init__()` (instance stability for broadcast wiring).
- Persistence failure is non-fatal — the pipeline starts without it.
- The atomic swap: add QueueHandler FIRST, then remove StreamHandler. Never the reverse.
- `asyncio.to_thread()` for QueueListener.stop() prevents blocking the event loop on the sentinel.
- Follow the SessionManager pattern for constructor injection (`*, stream_handler` kwarg).
- Import `LoggingService` in core.py — watch for circular imports (use TYPE_CHECKING if needed for type annotations only).

## Verify
- [ ] FR#1: LoggingService exists in the service tree with depends_on=[DatabaseService]
- [ ] FR#2: on_initialize creates and starts the full async pipeline (QueueHandler + QueueListener + all handlers)
- [ ] FR#3: on_shutdown stops QueueListener, drains pending records, flushes persistence handler
- [ ] FR#4: LogPersistenceHandler receives DatabaseService at construction — no set_database()
- [ ] FR#6: Sync→async swap test logs N records before on_initialize() and M records after; all N+M records appear in the capture handler buffer and stream output
- [ ] AC#1: LoggingService appears in the Resource tree and initializes after DatabaseService
- [ ] AC#2: After init, log records are persisted without any post-hoc wiring call
- [ ] AC#3: Shutting down stops persistence before database closes
- [ ] AC#5: No log records lost during sync→async transition (test verifies)
- [ ] AC#10: QueueListener is running and dispatching to all three handlers after init
