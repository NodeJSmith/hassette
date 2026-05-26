---
task_id: "T04"
title: "Remove module globals and migrate logging tests"
status: "planned"
depends_on: ["T03"]
implements: ["FR#8", "FR#9", "AC#6", "AC#7", "AC#9", "AC#11"]
---

## Summary
Remove all module-level globals, accessors, and `shutdown_logging()` from `logging_.py`. Migrate ~40 tests in `test_logging.py` from `enable_logging()`/`shutdown_logging()` to a local `logging_pipeline` pytest fixture. Update `before_shutdown()` to remove logging cleanup. Update `test_core.py` expected children lists and before_shutdown assertions. This is the cleanup task that eliminates the dual-state risk.

## Prompt
1. Remove from `src/hassette/logging_.py`:
   - Module globals: `_log_capture_handler`, `_log_persistence_handler`, `_queue_listener`
   - Accessor functions: `get_log_capture_handler()`, `get_log_persistence_handler()`
   - `shutdown_logging()` function
   - `enable_logging()` function (the temporary wrapper from T02)
   - Remove any remaining imports only needed by the removed code

2. Update `src/hassette/core/core.py`:
   - Remove `shutdown_logging` from the import line
   - Remove `get_log_persistence_handler` from the import line
   - Remove `shutdown_logging()` call from `before_shutdown()` (line 619)
   - Update `get_log_records_dropped()` to use `self.logging_service.dropped_count` (should already be done in T03, verify)

3. Update `src/hassette/core/runtime_query_service.py`:
   - Remove `get_log_capture_handler` and `get_log_persistence_handler` imports
   - Remove `DatabaseService` from `depends_on`, add `LoggingService`:
     ```python
     from hassette.core.logging_service import LoggingService
     depends_on: ClassVar[list[type[Resource]]] = [BusService, StateProxy, AppHandler, LoggingService]
     ```
   - Remove the `set_database()` block (lines 142-152)
   - Change broadcast wiring to:
     ```python
     handler = self.hassette.logging_service.capture_handler
     handler.set_broadcast(self.broadcast, loop)
     ```
   - Update the class docstring to remove mention of DatabaseService for persistence wiring

4. Create `logging_pipeline` pytest fixture in `tests/unit/conftest.py` (or a dedicated `tests/unit/logging_fixtures.py` if conftest is large):
   ```python
   @pytest.fixture
   def logging_pipeline():
       """Local logging pipeline for unit tests — no module globals.

       Covers stream + capture only. Tests needing persistence should
       construct LogPersistenceHandler directly with a mock db_service.
       """
       stream = StringIO()
       formatter = <create ProcessorFormatter matching production config>
       stream_handler = logging.StreamHandler(stream)
       stream_handler.setFormatter(formatter)
       capture = LogCaptureHandler(buffer_size=100)
       q = queue.Queue(maxsize=100)
       queue_handler = logging.handlers.QueueHandler(q)
       queue_handler.addFilter(CorrelationFilter())
       listener = HassetteQueueListener(q, stream_handler, capture)
       listener.start()
       logger = logging.getLogger("hassette")
       logger.addHandler(queue_handler)
       yield LoggingPipelineFixture(stream, stream_handler, capture, listener, queue_handler, logger)
       listener.stop()
       logger.removeHandler(queue_handler)
   ```

5. Migrate `tests/unit/test_logging.py`:
   - Remove `cleanup_logging` autouse fixture
   - Remove all `enable_logging()`/`shutdown_logging()` calls
   - Tests that test the full pipeline → use `logging_pipeline` fixture
   - Tests that test individual components (CorrelationFilter, LogCaptureHandler) → continue constructing directly, no fixture needed
   - Tests that test LogPersistenceHandler → construct with mock db_service directly (constructor injection)
   - ~40 tests affected, changes are mechanical

6. Update `tests/integration/test_core.py`:
   - Add `LoggingService` to expected children in `test_constructor_registers_background_services`
   - Add `LoggingService` to `test_init_order_contains_all_children`
   - Update `test_before_shutdown_removes_listeners_and_finalizes` — verify `before_shutdown()` does NOT do any logging cleanup
   - Update `test_before_shutdown_finalizes_even_when_listener_removal_fails` — same

7. Update `tests/e2e/conftest.py`:
   - Lines 237, 240: change the patch target from `hassette.core.runtime_query_service.get_log_capture_handler` to mock `hassette.logging_service.capture_handler` on the mock hassette instance

8. Update `tests/unit/core/test_runtime_query_service.py`:
   - Remove any mocks of `command_executor.repository` for persistence wiring

9. Run full test suite: `timeout 300 uv run pytest tests/unit/ tests/integration/ -v -n 2`

## Focus
- The `logging_pipeline` fixture must mirror production config enough for tests to be valid (structlog processors, formatter) but stay self-contained (no module state).
- `tests/e2e/conftest.py` patches `get_log_capture_handler` at the module level of RuntimeQueryService — since that import is removed, the patch target changes entirely. The e2e fixture should mock `hassette.logging_service.capture_handler` directly on the mock hassette.
- The before_shutdown tests currently don't assert on `shutdown_logging()` — they need an explicit check that it's NOT there (function is removed, so import would fail if someone re-adds it).
- `__main__.py` was already updated in T02 — verify it doesn't import `enable_logging`.
- `test_log_records_retention.py` fixture was updated in T01 — verify no stale `repository` references remain.

## Verify
- [ ] FR#8: RuntimeQueryService contains no logging persistence wiring code (no set_database, no get_log_persistence_handler)
- [ ] FR#9: before_shutdown() contains no logging-specific cleanup
- [ ] AC#6: RuntimeQueryService does not import `get_log_capture_handler`, `get_log_persistence_handler`, or `TelemetryRepository`
- [ ] AC#7: command_executor.repository is not accessed by any code outside CommandExecutor
- [ ] AC#9: Full test suite passes with no behavioral changes
- [ ] AC#11: before_shutdown() contains no logging cleanup code
