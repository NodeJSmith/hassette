# Design: Logging Service

**Date:** 2026-05-26
**Status:** approved
**Scope-mode:** expand
**Research:** N/A — architecture investigation conducted inline

## Problem

The logging infrastructure operates outside the Resource lifecycle. A module-level `enable_logging()` function creates handler instances, a QueueListener, and module-level globals during `Hassette.__init__()` — before the Resource tree exists. Database wiring happens later via a `set_database()` call from an unrelated service (RuntimeQueryService), requiring an awkward traversal through `hassette.command_executor.repository` to reach a method (`insert_log_records`) that is pure infrastructure SQL with no domain logic.

Shutdown ordering relies on a `before_shutdown()` hook calling `shutdown_logging()` before DatabaseService closes — an implicit contract enforced by code placement rather than the dependency graph.

This means logging is the only subsystem that: (a) creates stateful components outside the Resource tree, (b) uses late-wiring instead of constructor injection, (c) relies on manual shutdown ordering instead of `depends_on`. The cost is architectural debt: every other subsystem follows the Resource lifecycle pattern, making logging a one-off exception that new contributors must learn separately, that resists refactoring (e.g., reordering service initialization requires understanding the implicit `before_shutdown` contract), and that blocks future work requiring logging-service coordination (e.g., log-level runtime changes, health status integration).

## Goals

- Logging infrastructure participates in the Resource lifecycle with proper initialization ordering and shutdown guarantees
- LogPersistenceHandler receives its database dependency via constructor injection, not post-hoc wiring
- The QueueListener's lifecycle is owned by a single Resource with deterministic startup and shutdown
- The `insert_log_records` SQL method lives on the service that owns the database connection, not on a command-execution telemetry class
- No log records are lost during the transition from basic to full logging pipeline
- Basic console logging remains available from the first line of `Hassette.__init__()` before any Resource is constructed

## Non-Goals

- Changing the structlog configuration, processor chain, or formatter pipeline (those stay as-is)
- Adding new logging features (log levels UI, new filters, new output formats)
- Restructuring `LogCaptureHandler` or the WS broadcast mechanism (that stays on RuntimeQueryService)

## User Scenarios

### Framework Developer: Maintainer debugging startup issues

- **Goal:** Understand the initialization order of logging relative to other services
- **Context:** Investigating why log records are dropped during startup

#### Startup with two-phase logging

1. **System begins construction**
   - Sees: console output from all components during early construction
   - Then: logging service initializes after the database is ready
2. **Logging service completes initialization**
   - Sees: logging transitions from synchronous to asynchronous pipeline without record loss
   - Then: all subsequent records flow to console, in-memory buffer, and persistent storage
3. **Persistence is ready immediately**
   - Sees: no dropped records due to late wiring — storage is available from the moment the full pipeline starts
   - Then: records are persisted to the database without a separate wiring step

### Framework Developer: Debugging shutdown ordering

- **Goal:** Confirm log records are flushed before the database closes
- **Context:** Investigating data loss during unclean shutdown

#### Shutdown via dependency graph

1. **Shutdown begins — logging service shuts down first**
   - Sees: remaining records are drained and flushed to persistent storage
   - Then: logging service marks itself stopped
2. **Database shuts down after logging**
   - Sees: no more write requests arriving — logging already stopped
   - Then: database connection closes cleanly

### Framework Developer: Diagnosing logging service failure

- **Goal:** Understand what happens when the logging service cannot initialize
- **Context:** Database is corrupted or unavailable; system must still produce console output

#### Degraded mode — persistence creation fails

1. **System starts, persistence handler creation fails during logging service initialization**
   - Sees: console output and in-memory capture continue working (async pipeline starts without persistence)
   - Then: logging service marks itself ready with a warning — WS broadcast and console output are unaffected
2. **Operator investigates**
   - Sees: no log persistence (records not written to storage), but console output, ring buffer, and WS broadcast all function normally
   - Then: operator must restart the process to recover persistence (Resources do not auto-restart)

## Functional Requirements

- **FR#1** A dedicated logging service exists in the service tree and initializes after the database service
- **FR#2** The logging service creates and starts the full asynchronous logging pipeline during initialization
- **FR#3** The logging service stops the background listener, drains pending records, and flushes persistent storage before returning during shutdown
- **FR#4** The persistence handler receives its database dependency at construction time — no post-hoc wiring step
- **FR#5** Basic synchronous console logging is available before the service tree is constructed
- **FR#6** The logger transitions from synchronous to asynchronous pipeline without losing records during the swap
- **FR#7** The database service exposes a private method for batch-inserting log records into persistent storage (callable only via `enqueue()`)
- **FR#8** The runtime query service contains no logging persistence wiring code
- **FR#9** The coordinator's pre-shutdown hook contains no logging cleanup — shutdown is handled by the logging service lifecycle
- **FR#10** The runtime query service accesses the capture handler via the logging service for WebSocket broadcast wiring

## Edge Cases

- **Records emitted during the sync-to-async swap**: The swap must be atomic with respect to the handler list. Adding the async handler before removing the sync handler creates a brief overlap where records go to both — acceptable (duplication over loss). Removing sync after adding async ensures no gap.
- **Logging service initialization failure**: If persistence handler creation fails, the async pipeline still starts with stream + capture handlers. Console output, ring buffer, and WS broadcast all function normally — only persistence is lost. If the entire `on_initialize()` fails for an unexpected reason, basic synchronous logging continues working via the Phase 1 StreamHandler.
- **Shutdown-time logging**: After the logging service shuts down, further log records from other services still shutting down need a path. Restoring the synchronous handler ensures late logs reach the console.
- **Force-terminate drops records (accepted)**: When `_force_terminal()` fires (total shutdown timeout), `on_shutdown()` is skipped entirely. The QueueListener never stops cleanly and pending records are lost. This is the same behavior as today and is accepted — the system is already in a degraded state when force-terminate fires.
- **Sentinel blocking on full queue**: `QueueListener.stop()` calls `enqueue_sentinel()` which uses blocking `queue.put()`. If the log queue is full, this blocks the event loop thread. Mitigated by calling `_queue_listener.stop()` via `asyncio.to_thread()` with an explicit timeout (5s) in `on_shutdown()`.
- **Test isolation**: Unit tests that test logging components directly (not through the full lifecycle) must still be able to construct and tear down handlers independently.

## Acceptance Criteria

- **AC#1** The logging service appears in the service tree and initializes after the database service (FR#1)
- **AC#2** After initialization, log records are persisted to storage without any post-hoc wiring call (FR#4)
- **AC#3** Shutting down the service tree stops log persistence before closing the database connection (FR#3)
- **AC#4** Console output is available from the first log statement during system construction (FR#5)
- **AC#5** No log records are lost during the transition from synchronous to asynchronous pipeline (FR#6)
- **AC#6** The runtime query service contains no persistence wiring code and does not reference the telemetry repository (FR#8)
- **AC#7** The command executor's repository is not accessed by any code outside of the command executor itself (FR#8)
- **AC#8** The private batch log insertion method on DatabaseService produces equivalent SQL output to the previous TelemetryRepository implementation; tests verify via a test-specific database connection (FR#7)
- **AC#9** Existing test suites pass with no behavioral changes to log output format, correlation IDs, or persistence semantics
- **AC#10** After the logging service initializes, the background listener is running and dispatching records to all three handlers (stream, capture, persistence) (FR#2)
- **AC#11** The coordinator's `before_shutdown()` method contains no logging-specific cleanup (FR#9)
- **AC#12** The runtime query service accesses the capture handler through the logging service property, not through a module-level global or direct construction (FR#10)

## Key Constraints

- The sync→async swap must not lose records. Add QueueHandler before removing StreamHandler.
- `enable_basic_logging()` must not reference DatabaseService, LoggingService, or any Resource — it runs before the tree exists.
- Module-level globals (`_log_capture_handler`, `_log_persistence_handler`, `_queue_listener`) and their accessors (`get_log_capture_handler()`, `get_log_persistence_handler()`, `shutdown_logging()`) are removed. LoggingService is the single source of truth. Tests use a local fixture instead of module-level cleanup.
- LoggingService must not depend on RuntimeQueryService (would create a cycle). The broadcast wiring direction is: RuntimeQueryService depends on LoggingService, not the reverse.
- Initialization ordering is enforced via `depends_on`, not code placement. Services needing async logging during init declare `LoggingService` in their `depends_on`.

## Dependencies and Assumptions

- DatabaseService must be ready before LoggingService can initialize (enforced by `depends_on`)
- The existing QueueHandler/QueueListener/CorrelationFilter implementation is correct and battle-tested — we're moving it, not rewriting it
- Tests that previously called `enable_logging()`/`shutdown_logging()` will migrate to a pytest fixture that constructs a local pipeline
- The `hassette` logger name and structlog configuration remain unchanged

## Architecture

### Two-phase logging model

**Phase 1 — `enable_basic_logging()` (called in `Hassette.__init__()`):**
- Configures structlog (shared_processors, ProcessorFormatter, renderer selection)
- Creates a synchronous StreamHandler with the ProcessorFormatter
- Attaches it directly to the `hassette` logger (no queue, no background thread)
- Sets log level, captures warnings, suppresses noisy libraries
- Returns the StreamHandler instance (stored on `Hassette` as `self._basic_stream_handler`, passed to LoggingService in `wire_services()`)

**Phase 2 — `LoggingService.on_initialize()`:**
- Defensive cleanup: removes any existing QueueHandler instances from the `hassette` logger and stops any running QueueListener (idempotent guard against double-initialization)
- Builds handler list unconditionally: `[self._stream_handler, self.capture_handler]` (capture_handler created once in `__init__`, stable across re-initialization)
- Attempts persistence handler creation (best-effort): `LogPersistenceHandler(db_service, loop)`. If this fails, logs an error and continues without persistence — the async pipeline still starts with stream + capture
- Creates a bounded Queue + QueueHandler with CorrelationFilter
- Creates HassetteQueueListener(queue, *handlers) — includes persistence handler only if creation succeeded
- Atomically swaps the logger: adds QueueHandler, then removes the direct StreamHandler
- Starts the QueueListener
- Calls `mark_ready()` unconditionally — the pipeline is running regardless of persistence status

**LoggingService.on_shutdown():**
- Sets `capture_handler.shutting_down = True`
- Logs a warning: "LoggingService shutting down — subsequent log records will be console-only"
- Removes QueueHandler from logger
- Re-attaches the direct StreamHandler (for shutdown-time logs from other services)
- Stops the QueueListener via `asyncio.to_thread()` with 5s timeout (drains queue without blocking event loop)
- Flushes persistence handler

### Trade-offs

This architecture optimizes for lifecycle consistency (every subsystem follows the same Resource pattern) and proper dependency ordering (shutdown guaranteed by the graph). It sacrifices simplicity of the startup path — the two-phase swap introduces a brief period of synchronous logging and requires careful handler ordering to avoid record loss. It also introduces a Resource for something that previously "just worked" via module globals, increasing the surface area of the Resource tree by one node. The async pipeline (QueueListener + stream + capture) is unconditional; only persistence degrades gracefully on failure.

### LoggingService class structure

```python
class LoggingService(Resource):
    depends_on = [DatabaseService]

    capture_handler: LogCaptureHandler
    persistence_handler: LogPersistenceHandler | None

    def __init__(self, hassette, *, stream_handler, parent=None):
        super().__init__(hassette, parent=parent)
        self._stream_handler = stream_handler
        self.capture_handler = LogCaptureHandler(buffer_size=hassette.config.web_api.log_buffer_size)

    async def on_initialize(self):
        # Defensive cleanup (idempotent guard)
        # Build handler list: [stream_handler, capture_handler]
        # Try persistence handler creation (best-effort)
        # Create Queue + QueueHandler + CorrelationFilter
        # Create HassetteQueueListener with available handlers
        # Atomic swap: add QueueHandler, remove StreamHandler
        # Start listener
        self.mark_ready(reason="LoggingService initialized")

    async def on_shutdown(self):
        # Set capture_handler.shutting_down
        # Log "subsequent logs will be console-only"
        # Remove QueueHandler, restore StreamHandler
        # Stop QueueListener via asyncio.to_thread() with 5s timeout
        # Flush persistence handler
        ...
```

LoggingService is a Resource, not a Service — the QueueListener manages its own background thread. No `serve()` method or `RestartSpec` is needed. The async pipeline starts unconditionally; only persistence degrades gracefully on failure.

### insert_log_records on DatabaseService

Move from `TelemetryRepository` to `DatabaseService` as a private method (matching the existing `_do_*`/`_check_*` convention — all write coroutines on DatabaseService are private to prevent direct-await misuse that would bypass the serialized write worker):

```python
class DatabaseService(Service):
    async def _insert_log_records(self, records: list[dict]) -> None:
        """Batch-insert log records into the log_records table.

        Must only be called via enqueue() — never await directly.
        """
        if not records:
            return
        db = self.db
        try:
            await db.execute("BEGIN")
            await db.executemany(_LOG_INSERT_SQL, records)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
```

The `_LOG_COLUMNS` and `_LOG_INSERT_SQL` constants move with it.

### LogPersistenceHandler constructor injection

```python
class LogPersistenceHandler(logging.Handler):
    def __init__(self, db_service: DatabaseService, loop: asyncio.AbstractEventLoop, persistence_level: int = logging.INFO):
        super().__init__()
        self._db_service = db_service
        self._loop = loop
        # No set_database() needed — ready from construction
```

The `_flush()` method changes from `db_service.enqueue(repository.insert_log_records(batch))` to `db_service.enqueue(db_service._insert_log_records(batch))`.

### No module-level globals

The following are removed entirely:
- `_log_capture_handler`, `_log_persistence_handler`, `_queue_listener` globals
- `get_log_capture_handler()`, `get_log_persistence_handler()` accessors
- `shutdown_logging()` function

LoggingService is the single owner of all pipeline state. Production code accesses handlers via `hassette.logging_service.capture_handler` and `hassette.logging_service.persistence_handler`.

`Hassette.get_log_records_dropped()` changes from calling `get_log_persistence_handler()` to reading `self.logging_service.persistence_handler.dropped_count` directly (returning 0 if `persistence_handler` is None).

Tests use a `logging_pipeline` pytest fixture that constructs a local QueueListener + handlers and tears them down after the test — no shared module state.

### RuntimeQueryService changes

- Remove `DatabaseService` from `depends_on` (it was only there for persistence wiring)
- Add `LoggingService` to `depends_on` (for capture handler access)
- Remove the `set_database()` block (lines 142-152)
- Change broadcast wiring to access capture handler via LoggingService:
  ```python
  handler = self.hassette.logging_service.capture_handler
  handler.set_broadcast(self.broadcast, loop)
  ```

### Wiring in wire_services()

```python
# In Hassette.__init__():
self._basic_stream_handler = enable_basic_logging(...)  # returns the StreamHandler

# In wire_services():
self._logging_service = self.add_child(LoggingService, stream_handler=self._basic_stream_handler)
```

Placed after `self._database_service = self.add_child(DatabaseService)`. Services that require guaranteed async logging during their `on_initialize()` declare `LoggingService` in their `depends_on` — the topological sort ensures they initialize after the async pipeline is running. RuntimeQueryService already requires this (for capture handler access). Other services (CommandExecutor, BusService) initialize in the same wave as LoggingService but don't log heavily during init, so no additional `depends_on` declarations are needed today.

If `stream_handler` is `None` (test context where `enable_basic_logging()` was not called), the swap step in `on_initialize()` is skipped with a warning log.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `enable_logging()` in `logging_.py` | `enable_basic_logging()` + `LoggingService.on_initialize()` | Rewrite — split into two functions |
| `get_log_capture_handler()`, `get_log_persistence_handler()`, `shutdown_logging()` | Direct access via `hassette.logging_service.*`; test fixture for test cleanup | Remove functions and module globals entirely |
| `LogPersistenceHandler.set_database()` | Constructor injection in `LogPersistenceHandler.__init__()` | Remove method entirely |
| `TelemetryRepository.insert_log_records()` + `_LOG_COLUMNS` + `_LOG_INSERT_SQL` | `DatabaseService._insert_log_records()` | Move to database_service.py, remove from telemetry_repository.py |
| `RuntimeQueryService` lines 142-152 (persistence wiring) | LoggingService owns this | Remove block |
| `Hassette.before_shutdown()` line 619 (`shutdown_logging()`) | `LoggingService.on_shutdown()` | Remove line |
| `RuntimeQueryService.depends_on` includes `DatabaseService` | Replaced by `LoggingService` in depends_on | Swap dependency |

## Convention Examples

### Resource with constructor injection (SessionManager pattern)

**Source:** `src/hassette/core/session_manager.py`

```python
class SessionManager(Resource):
    bus: Bus

    def __init__(
        self,
        hassette: "Hassette",
        *,
        database_service: "DatabaseService",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._database_service = database_service
        self.bus = self.add_child(Bus)
        self._session_id: int | None = None
        self._session_lock = asyncio.Lock()

    async def on_initialize(self) -> None:
        self.bus.on(...)
        self.mark_ready(reason="SessionManager initialized")
```

### Service with depends_on and lifecycle

**Source:** `src/hassette/core/command_executor.py`

```python
class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
    )

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue(maxsize=hassette.config.database.telemetry_write_queue_max)
        self.repository = TelemetryRepository(hassette.database_service)
```

### DatabaseService.enqueue() for fire-and-forget writes

**Source:** `src/hassette/core/database_service.py`

```python
def enqueue(self, coro: Coroutine[Any, Any, Any]) -> bool:
    """Submit a coroutine for fire-and-forget execution."""
    if self._db_write_queue is None:
        coro.close()
        raise RuntimeError("DatabaseService.enqueue() called before on_initialize()")
    try:
        self._db_write_queue.put_nowait((coro, None))
    except asyncio.QueueFull:
        coro.close()
        self.logger.error("DB write queue full (%d items) — dropping", self._db_write_queue.qsize())
        return False
    return True
```

### Wiring services with constructor injection in wire_services()

**Source:** `src/hassette/core/core.py`

```python
self._session_manager = self.add_child(SessionManager, database_service=self._database_service)
```

## Alternatives Considered

**A. Keep `enable_logging()` as-is, just move wiring (Hold approach):**
LoggingService only handles the `set_database()` late-wiring and `shutdown_logging()` call. Simpler, lower risk. Rejected because it preserves the anti-pattern of creating LogPersistenceHandler before its dependency is available, requiring a two-step initialization (construct inert, then wire later).

**B. Move TelemetryRepository ownership to DatabaseService (issue #866's original proposal):**
The entire repository moves to DatabaseService. Rejected because it mixes abstraction levels — DatabaseService is connection/migration infrastructure while TelemetryRepository contains domain-specific write logic for command execution telemetry. Only `insert_log_records` (pure SQL, no domain logic) belongs on DatabaseService.

**C. Keep insert_log_records on TelemetryRepository, pass repository to LoggingService:**
LoggingService would depend on both DatabaseService and CommandExecutor's repository. Rejected because it preserves the cross-service coupling and makes LoggingService depend on command execution infrastructure.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/core/test_log_records.py` — `TestInsertLogRecords` class uses `TelemetryRepository.insert_log_records()` via a `repo` fixture. Update fixture to use `DatabaseService.insert_log_records()` instead.
- `tests/unit/test_logging.py` — Major update: remove all `enable_logging()`/`shutdown_logging()` usage. Replace with a `logging_pipeline` pytest fixture that constructs a local QueueListener + handlers and tears them down. Update LogPersistenceHandler tests for constructor injection. ~40 tests affected but changes are mechanical (fixture swap).
- `tests/integration/test_core.py` — `test_before_shutdown_removes_listeners_and_finalizes` and `test_before_shutdown_finalizes_even_when_listener_removal_fails` — verify `before_shutdown()` contains no logging-specific cleanup (the `shutdown_logging()` call is removed, not patched).
- `tests/unit/core/test_runtime_query_service.py` — If any tests mock `command_executor.repository` for persistence wiring, remove those mocks.
- `tests/integration/test_core.py` — `test_constructor_registers_background_services` and `test_init_order_contains_all_children` — add `LoggingService` to the expected children lists.

### New Test Coverage

- **`logging_pipeline` fixture** (test infrastructure): Shared fixture that constructs a local QueueListener + stream/capture/persistence handlers, yields them, and tears down on exit. Used by all unit tests that test logging components in isolation. No module-level state.
- **LoggingService initialization** (FR#1, FR#2): Verify LoggingService appears in Resource tree with correct depends_on; verify on_initialize creates all handlers and starts QueueListener
- **Constructor injection** (FR#4): Verify LogPersistenceHandler receives DatabaseService at construction and can persist immediately without additional wiring
- **Sync→async swap** (FR#6): Log records before and after LoggingService initializes; verify all records arrive at their destinations (no loss during transition)
- **Graceful persistence degradation** (edge case): Verify that if persistence handler creation fails, QueueListener still starts with stream + capture; WS broadcast works
- **Shutdown ordering** (FR#3): Verify LoggingService.on_shutdown() flushes pending records and stops QueueListener before returning
- **DatabaseService._insert_log_records** (FR#7): Unit test the method via a test-specific database connection (can reuse existing test patterns from TestInsertLogRecords)
- **Post-shutdown logging** (edge case): Verify that logs emitted after LoggingService shuts down still reach console output (StreamHandler restored)

### Tests to Remove

- No tests to remove outright — existing tests are adapted rather than deleted. The `repo` fixture in `test_log_records.py` changes to use DatabaseService but the test logic remains.

## Documentation Updates

- `CLAUDE.md` — Update the "Core Components" section to mention LoggingService as a service in the architecture overview. Add LoggingService to the list of services in wire_services() ordering if documented.
- No user-facing documentation affected (this is internal framework plumbing with no API changes).

## Impact

<!-- Gap check 2026-05-26: 3 gaps included — __main__.py:2 (enable_logging import) → T02 Prompt item 4, e2e/conftest.py:237,240 (get_log_capture_handler patch) → T04 Prompt item 7, test_log_records_retention.py (repo.insert_log_records calls) → T01 Prompt item 5 -->

### Changed Files

- `src/hassette/logging_.py` — Major rewrite: split `enable_logging()` into `enable_basic_logging()`, update `LogPersistenceHandler` to constructor injection, remove `shutdown_logging()` and all module-level globals/accessors
- `src/hassette/core/logging_service.py` — **New file**: LoggingService Resource
- `src/hassette/core/database_service.py` — Add `_insert_log_records()` method + `_LOG_COLUMNS`/`_LOG_INSERT_SQL` constants
- `src/hassette/core/telemetry_repository.py` — Remove `insert_log_records()`, `_LOG_COLUMNS`, `_LOG_INSERT_SQL`
- `src/hassette/core/core.py` — Replace `enable_logging()` with `enable_basic_logging()`, wire LoggingService in `wire_services()`, remove `shutdown_logging()` from `before_shutdown()`, expose `logging_service` property
- `src/hassette/core/runtime_query_service.py` — Remove persistence wiring, swap DatabaseService for LoggingService in depends_on, access capture handler via LoggingService
- `tests/unit/core/test_log_records.py` — Update `repo` fixture to use DatabaseService
- `tests/unit/test_logging.py` — Update LogPersistenceHandler tests for constructor injection
- `tests/integration/test_core.py` — Update before_shutdown tests
- `tests/unit/core/test_logging_service.py` — **New file**: LoggingService unit tests

### Behavioral Invariants

- Log output format (console and JSON) must not change
- Correlation IDs (execution_id, app_key, instance_name, instance_index, seq) must continue to be stamped on all records
- LogCaptureHandler's in-memory buffer and WS broadcast behavior must not change
- `dropped_count` combines both log-queue overflow and DB-write-queue overflow into a single counter. Separate per-queue counters are out of scope for this PR but tracked as a follow-up (#883)

### Blast Radius

- All services that log during initialization may see a brief behavioral difference (synchronous logging during startup instead of async) — functionally equivalent, slightly higher latency during init only
- RuntimeQueryService's depends_on list changes — verify no cascading initialization order issues
- Integration tests that construct full Hassette instances will exercise the new path automatically
- E2E tests exercise the full lifecycle and will validate end-to-end persistence

## Open Questions

None — architecture is fully determined from the prior investigation.
