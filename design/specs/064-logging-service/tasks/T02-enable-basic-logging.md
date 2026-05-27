---
task_id: "T02"
title: "Split enable_logging into enable_basic_logging"
status: "done"
depends_on: []
implements: ["FR#5", "AC#4"]
---

## Summary
Rewrite `enable_logging()` in `logging_.py` into `enable_basic_logging()` — a function that sets up synchronous console-only logging (structlog config + StreamHandler) and returns the StreamHandler. This is Phase 1 of the two-phase model: basic logging available before the Resource tree exists. The full async pipeline will be created by LoggingService in T03.

## Prompt
1. Read `src/hassette/logging_.py` lines 356–469 (current `enable_logging()`).

2. Create `enable_basic_logging()` that does only:
   - Stops any previously running listener (call internal cleanup — but no `shutdown_logging()` since that's being removed in T04)
   - Configures structlog (shared_processors, ProcessorFormatter, renderer selection) — same as today
   - Creates a synchronous StreamHandler with the ProcessorFormatter
   - Attaches it directly to the `hassette` logger
   - Sets log level, captures warnings, suppresses noisy libraries
   - Sets `sys.excepthook` and `threading.excepthook`
   - Returns the StreamHandler instance
   - Signature: `def enable_basic_logging(log_level, *, log_format="auto", stream=None) -> logging.StreamHandler`

   Things it does NOT do (moved to LoggingService):
   - Create LogCaptureHandler
   - Create LogPersistenceHandler
   - Create Queue/QueueHandler/CorrelationFilter
   - Create or start HassetteQueueListener
   - Set module-level globals

3. Keep `enable_logging()` as a deprecated wrapper that calls `enable_basic_logging()` and also sets up the full pipeline (for backward compat during the transition — T03/T04 will remove callers). This prevents breaking the existing test suite before T04 migrates them.

4. Update `src/hassette/__main__.py`:
   - Change `from hassette.logging_ import enable_logging` to `from hassette.logging_ import enable_basic_logging`
   - Change the call to `enable_basic_logging(get_log_level(), log_format="auto")`

5. Update `src/hassette/core/core.py`:
   - Change the import to use `enable_basic_logging`
   - Change `Hassette.__init__()` to call `enable_basic_logging(...)` and store the return value: `self._basic_stream_handler = enable_basic_logging(...)`
   - Keep all existing parameters passed through

6. Run: `timeout 300 uv run pytest tests/unit/test_logging.py -v -n 2`

## Focus
- `enable_basic_logging()` must NOT reference DatabaseService, LoggingService, or any Resource — it runs before the tree exists.
- The function must be importable without triggering circular imports (it's called from `__main__.py` and `core.py`).
- Keep `enable_logging()` temporarily for test compat — T04 handles the full test migration.
- The returned StreamHandler is stored on Hassette and later passed to LoggingService in wire_services().
- `log_buffer_size` and `log_persistence_level` params are NOT needed on `enable_basic_logging()` — they move to LoggingService config.

## Verify
- [ ] FR#5: `enable_basic_logging()` provides synchronous console logging and returns the StreamHandler
- [ ] AC#4: Console output is available from the first log statement during system construction (verified by existing test suite passing)
