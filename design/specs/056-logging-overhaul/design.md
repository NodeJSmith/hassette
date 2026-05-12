# Design: Logging Overhaul

**Date:** 2026-05-12
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-05-02-logging/research.md

## Problem

When multiple automations fire concurrently, their log output interleaves into a single undifferentiated stream. There is no way to see which invocation produced which log line. Debugging requires mentally reconstructing which records belong together — a process that fails as concurrency increases.

All log records are stored in memory only. Every restart erases history. If an automation misbehaved overnight or during an absence, there is no record to investigate. The only evidence is the current session's ring buffer.

The console output library is unmaintained and incompatible with the latest Python runtime. Production deployments (containers) receive human-formatted text instead of machine-parseable structured output.

## Goals

- Every log record emitted during a handler or job execution carries a correlation identifier linking it to that specific invocation
- Log records survive process restarts and are queryable by time, application, level, and correlation identifier
- A user can navigate from an error on the logs page to the specific invocation's log output in two clicks or fewer
- Console output uses colored human-readable format in development and structured machine-parseable format in production, determined automatically with manual override
- Log emission from the event loop is non-blocking

## Non-Goals

- Runtime log level UI toggle (the backend API endpoint is in scope; the UI is not)
- Execution replay timeline or step-by-step visualization
- Distributed tracing or third-party observability integration
- Changing per-app or per-service log level configuration patterns

## User Scenarios

### Operator: Technical hobbyist running automations

- **Goal:** Diagnose why an automation failed or behaved unexpectedly
- **Context:** Opens the monitoring UI after noticing unexpected behavior, or after a restart when something went wrong overnight

#### Live debugging — concurrent handler failure

1. **Opens the logs page**
   - Sees: Recent log entries with level, timestamp, app name, source function, and message
   - Decides: Filters to ERROR level to find the failure
   - Then: System highlights error entries; each carries a correlation identifier

2. **Identifies the failing invocation**
   - Sees: Error log entry with app name, message, and correlation identifier
   - Decides: Clicks through to view all logs from that specific invocation
   - Then: System navigates to a filtered view showing only log records from that invocation

3. **Reads the full invocation log**
   - Sees: Chronological log output from the single invocation — setup, execution, and error
   - Decides: Whether the cause is clear or requires further investigation
   - Then: Navigates to the app detail page or closes the tab

#### Post-restart investigation

1. **Opens the logs page after a restart**
   - Sees: Historical log entries from before the restart, queryable by time range
   - Decides: Filters to the time window when the problem occurred
   - Then: System returns persisted log records matching the filter

2. **Narrows to the failing app**
   - Sees: Filtered historical logs from the specific app during the problem window
   - Decides: Identifies the invocation that failed
   - Then: Clicks through to the per-invocation view

#### Per-invocation logs from app detail

1. **Views an invocation on the app detail page**
   - Sees: Invocation row with status, duration, and execution identifier
   - Decides: Expands the row to see details
   - Then: System shows invocation metadata plus a full inline log table showing all records from that execution, with sorting and level filtering

## Functional Requirements

- **FR#1** Every log record emitted during a handler invocation or job execution is stamped with the execution's correlation identifier before it leaves the calling context
- **FR#2** Log records emitted outside any execution context (startup, shutdown, framework housekeeping) carry no correlation identifier and are attributed as framework-tier
- **FR#3** Child tasks spawned during an execution inherit the correlation identifier via context propagation
- **FR#4** The console output library is replaced with a structured logging library that supports composable processor chains
- **FR#5** Console output renders as colored human-readable text when the output stream is a terminal, and as one-JSON-object-per-line when it is not
- **FR#6** A configuration field overrides the automatic format detection
- **FR#7** Existing log statements in user application code produce structured output with correlation identifiers without any code changes
- **FR#8** Log emission from application code on the event loop is a non-blocking enqueue operation; all log I/O executes in a background thread
- **FR#9** The background log processing thread is flushed and drained during shutdown before connections are closed, with no records lost during clean shutdown
- **FR#10** Log records are persisted to the database with timestamp, level, logger name, function name, line number, message, exception info, application key, application instance name, application instance index, execution correlation identifier, and source tier
- **FR#11** Persisted log records are filtered by a configurable minimum level, defaulting to INFO
- **FR#12** A time-based retention policy deletes persisted log records older than a configurable threshold, defaulting to 3 days
- **FR#13** The database size failsafe includes persisted log records in its cleanup when the size limit is exceeded
- **FR#14** The log REST endpoint returns persisted records with filtering by time range, application, level, and execution correlation identifier, with limit-based pagination
- **FR#15** The real-time log stream continues to deliver records via the existing broadcast mechanism with correlation identifiers included in the payload
- **FR#16** The logs page supports an execution correlation identifier as a URL parameter, showing only records from that execution when present
- **FR#17** The app detail page shows a full inline log table when an invocation or job execution row is expanded, pre-filtered to that execution's correlation identifier, with sorting and level filtering
- **FR#18** Noisy third-party library log suppression continues to work as it does today
- **FR#19** A REST endpoint accepts a logger name and a level, and changes that logger's effective level at runtime without requiring a restart

## Edge Cases

- **No execution context**: Framework-level logs (startup, shutdown, retention cleanup) have no execution_id. The persistence handler must accept null execution_id. The frontend must handle log records with no correlation identifier gracefully.
- **Execution spawns sub-tasks**: Asynchronous child tasks spawned during an execution inherit the correlation identifier. This is the desired behavior — all work within an invocation shares the same correlation.
- **High log volume**: A busy system could produce thousands of log records per second. The persistence level filter (default INFO) and retention policy (default 3 days) bound growth. The size failsafe deletes log records first (highest volume table) when the database limit is approached.
- **Background queue overflow**: If log production outpaces the background thread's drain rate, the queue could grow unbounded. Use a bounded queue (configured via `log_queue_max`, default 2000); drop records with a rate-limited warning when full. Expose a `log_records_dropped` counter in the system health/status response so operators can distinguish "nothing happened" from "records were dropped during a burst."
- **Shutdown ordering**: The background log processing thread must flush before the database connection closes and before real-time stream clients are disconnected. Incorrect ordering loses final log records or raises errors on broadcast.
- **Mixed log sources**: Both framework-originated log records and user application log records must pass through the same processing pipeline and receive correlation identifiers.
- **Database not yet ready**: During early startup, before the database is initialized, log records should still appear on console and in the WS ring buffer. Persistence begins only after the database is available.
- **Empty execution logs**: An invocation that produces no log records (e.g., a trivial handler) should show an empty state in the inline preview, not an error.

## Acceptance Criteria

- **AC#1** Log records emitted during a handler invocation carry the invocation's correlation identifier. Verified by: trigger a handler, query persisted logs by correlation identifier, confirm all records from that invocation are returned and no records from other invocations are included. (FR#1, FR#3)
- **AC#2** Framework-level log records have no correlation identifier and are attributed as framework-tier. Verified by: query persisted logs with no correlation identifier, confirm they are startup/shutdown/housekeeping records. (FR#2)
- **AC#3** Console output is colored text when the output stream is a terminal and structured machine-parseable format when it is not. Verified by: run hassette in a terminal and confirm colored output; pipe stdout and confirm structured output. (FR#5)
- **AC#4** A configuration override forces structured output regardless of terminal detection. Verified by: set the format override, run in a terminal, confirm structured output instead of colored text. (FR#6)
- **AC#5** A user app using standard library logging produces structured output with correlation identifiers during handler execution. Verified by: write a test app that logs via the standard library, trigger it, confirm the console output and persisted records include the correlation identifier. (FR#7)
- **AC#6** Log records survive a process restart. Verified by: log some records, restart hassette, query the logs endpoint, confirm pre-restart records are returned. (FR#10, FR#14)
- **AC#7** Navigating to `/logs?execution_id=<uuid>` shows only log records from that execution. Verified by: click through from an error, confirm the filtered view contains only matching records. (FR#16)
- **AC#8** Expanding an invocation row on the app detail page shows a full inline log table filtered to that execution. Verified by: trigger a handler that logs multiple lines, expand the row, confirm the log table appears with correct records and supports sorting/filtering. (FR#17)
- **AC#9** Log records older than `log_retention_days` are deleted during retention cleanup. Verified by: set retention to 1 day, insert old records, trigger cleanup, confirm deletion. (FR#12)
- **AC#10** The previous console output library is removed from the project. Verified by: confirm it is not in the dependency manifest or any import statement. (FR#4)
- **AC#11** Records below the configured persistence level are not persisted to the database. Verified by: emit low-level diagnostic logs during a handler with persistence level set to INFO, query the database, confirm they are absent. (FR#11)
- **AC#12** The event loop is not blocked by log emission. Verified by: add timing instrumentation around a logger.info() call in a handler, confirm it completes in <1ms (enqueue only). (FR#8)
- **AC#13** No log records are lost during clean shutdown. Verified by: emit log records, initiate clean shutdown, confirm all emitted records appear in the database and on console output. (FR#9)
- **AC#14** The database size failsafe deletes log records when the size limit is exceeded. Verified by: insert log records until the database approaches the size limit, trigger the failsafe, confirm log records are deleted oldest-first. (FR#13)
- **AC#15** Real-time log stream messages include correlation identifiers. Verified by: connect a WebSocket client, trigger a handler invocation, confirm the streamed log messages contain the execution's correlation identifier. (FR#15)
- **AC#16** Noisy third-party library logs remain suppressed at WARNING level. Verified by: confirm that HTTP client and connection pool libraries do not produce INFO-level output on console or in the database. (FR#18)
- **AC#17** Calling the runtime log level endpoint with a logger name and level changes that logger's output immediately. Verified by: set a logger to DEBUG via the endpoint, emit a DEBUG log, confirm it appears; set it back to INFO, emit another DEBUG log, confirm it does not appear. (FR#19)

## Key Constraints

- The structured logging library must wrap stdlib logging, not replace it. User application code uses `logging.getLogger()` and must not require changes.
- The existing `CURRENT_EXECUTION_ID` context var in `context.py` must be reused — do not create a separate correlation ID mechanism.
- The logs table must not have a `session_id` foreign key. The sessions concept is being removed from the project.
- Correlation identifier reads (from the context var) must happen in the calling context (event loop thread), not in the background processing thread. This requires stamping the identifier before the record is enqueued.
- Shutdown ordering must be: stop accepting new records → flush background processing → close WebSocket clients → close database connections.

## Dependencies and Assumptions

- **structlog** (new dependency, >=24.4): Structured logging library with processor chain architecture and stdlib integration via `ProcessorFormatter`. Well-maintained, widely used in production Python services.
- **coloredlogs** (removed dependency): Currently used for console output. Unmaintained, Python 3.13+ compatibility issues.
- **Existing infrastructure**: `CURRENT_EXECUTION_ID` context var, `DatabaseService.enqueue()` for fire-and-forget writes, retention cleanup in `_do_run_retention_cleanup()` and `_check_size_failsafe()`, Alembic migration chain at version 008, frontend `LogTable` component with sorting/filtering/WS streaming, `InvocationDetail` component with expandable rows.
- **Assumption**: The `useScopedApi` hook's limit+since pagination pattern is appropriate for historical log queries.

## Architecture

### Layer 1: structlog migration

Replace `coloredlogs` in `enable_logging()` (`src/hassette/logging_.py`) with structlog's `ProcessorFormatter` approach:

1. Configure structlog with shared processors: `add_log_level`, `TimeStamper(fmt="iso")`, a custom `add_correlation_ids` processor (reads `CURRENT_EXECUTION_ID` from `context.py`), `merge_contextvars`
2. Use `ProcessorFormatter.wrap_for_formatter` as the final structlog processor
3. Create a `ProcessorFormatter` with `ConsoleRenderer` (dev) or `JSONRenderer` (prod), selected by `sys.stdout.isatty()` or the `log_format` config field
4. The `ProcessorFormatter`'s `foreign_pre_chain` handles stdlib `logging.getLogger()` records — adds the same structured fields

Add `log_format` config field to `HassetteConfig` in `config/config.py`: `log_format: Literal["auto", "console", "json"] = "auto"`.

Each Resource/Service logger gains structlog bound variables at creation time: `source_tier` ("app" or "framework") and the resource's `class_name`. The `unique_name` hierarchy and `_get_logger_name()` are preserved as-is — they remain needed for per-instance stdlib level control — but are no longer the source of truth for log attribution. The `register_app_logger()` prefix-matching mechanism and `_logger_to_app_key` dict in `LogCaptureHandler` are removed.

The existing per-app and per-service log level configuration (`*_log_level` fields) continues to work — structlog wraps stdlib, so logger hierarchy is preserved. Noisy library suppression stays as-is.

### Layer 2: Correlation ID binding

Two layers of context var binding, both using structlog's `bind_contextvars()`:

**Resource/service identity** — bound at two points using `bind_contextvars()` / `clear_contextvars()` pairs:

**Lifecycle hooks** (in `app_lifecycle_service.py`): Before each lifecycle hook call (`on_initialize`, `on_ready`, `on_shutdown`), bind `app_key`, `instance_name`, `instance_index`. After each hook completes, call `clear_contextvars()`. Lifecycle hooks are sequential (one app at a time), so there is no concurrency bleed risk. This ensures lifecycle hook logs carry app identity even though no `execution_id` exists.

**Handler/job execution** (in `command_executor.py`): Bind `app_key`, `instance_name`, `instance_index` alongside `CURRENT_EXECUTION_ID.set()` in `_execute_handler()` and `_execute_job()`. Call `clear_contextvars()` in the `finally` block after `CURRENT_EXECUTION_ID.reset(token)`. Each execution gets its own bind/clear cycle, preventing concurrency bleed between interleaved handler invocations from different apps. The `cmd` object already carries `app_key` and `instance_index` from the listener/job registration.

Framework service logs carry identity from `logger_name` and `source_tier` (logger-bound). Framework services do not bind `app_key`/`instance_name`/`instance_index` via context vars — they are attributed as framework-tier with no app identity, which is correct.

**Source tier** is NOT a context var — it is a structlog bound variable on each logger instance, set at logger creation time. `App` subclasses bind `source_tier="app"` on their logger; `Resource`/`Service` base classes bind `source_tier="framework"`. This ensures that during a handler invocation, the user's handler logs (through the App's logger) are tier="app" while per-app child resource logs (through their own loggers, e.g., the Bus instance) are tier="framework" — even though both share the same `execution_id` from the async context. The tier is a property of the code that emits the log, not the context it runs in.

**Execution identity** — the existing `CURRENT_EXECUTION_ID` context var is already bound in `command_executor.py:_execute_handler()` and `_execute_job()`. A structlog processor reads it:
```python
def add_execution_id(logger, method_name, event_dict):
    event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
    return event_dict
```

For stdlib `logging.getLogger()` callers (user app code), attach a `logging.Filter` to the `QueueHandler` that stamps `record.execution_id = CURRENT_EXECUTION_ID.get(None)` and reads the bound app identity vars **before** the record is enqueued. This ensures context vars are read in the calling context, not the background thread.

Update `LogEntry` dataclass to include `execution_id: str | None = None`, `instance_name: str | None = None`, `instance_index: int | None = None`, and `source_tier: str | None = None`. Source tier is bound as a structlog bound variable on each logger instance using the existing `Resource.source_tier` class attribute (`ClassVar[SourceTier]`).

The existing `register_app_logger()` prefix-matching approach in `LogCaptureHandler` is replaced by structlog context var binding. At app instance initialization (`app_lifecycle_service.py`), bind `app_key`, `instance_name`, and `instance_index` via `structlog.contextvars.bind_contextvars()`. These propagate to all log records emitted during the app's lifecycle — including startup/shutdown hooks (`on_initialize`, `on_ready`, `on_shutdown`) where no `execution_id` exists. The `_resolve_app_key()` method and `_logger_to_app_key` dict are removed.

### Layer 3: QueueHandler async dispatch

Replace the direct handler attachment with `QueueHandler` → `QueueListener`:

1. Attach a `logging.handlers.QueueHandler` (bounded queue, size from `log_queue_max`) to the `hassette` logger
2. Start a custom `QueueListener` subclass that overrides `dequeue()` with `queue.get(block=True, timeout=0.2)` — on `queue.Empty`, calls `LogPersistenceHandler.flush_if_pending()` to drain any partial batch. This single-threaded dequeue-timeout approach avoids a separate timer thread and eliminates shutdown races. Three handlers:
   - `StreamHandler` with `ProcessorFormatter` (console/JSON output)
   - `LogPersistenceHandler` (new — batches records and writes to DB via `DatabaseService.enqueue()`)
   - Modified `LogCaptureHandler` (ring buffer for WS broadcast)

The `LogCaptureHandler` retains the `call_soon_threadsafe` broadcast pattern but adds a `_shutting_down` flag checked in `emit()` to avoid `RuntimeError` on a closing event loop.

Add a `shutdown_logging()` function that stops the `QueueListener` (which flushes remaining records to all three handlers). Call `shutdown_logging()` from `Hassette.before_shutdown()` (`core.py:594`), which runs before `_shutdown_children()` — guaranteeing the QueueListener is drained before `DatabaseService` or WebSocket connections shut down.

### Layer 4: Database persistence

**Migration 009** creates the `log_records` table:

```sql
CREATE TABLE log_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seq             INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    level           TEXT NOT NULL,
    logger_name     TEXT NOT NULL,
    func_name       TEXT,
    lineno          INTEGER,
    message         TEXT NOT NULL,
    exc_info        TEXT,
    app_key         TEXT,
    instance_name   TEXT,
    instance_index  INTEGER,
    execution_id    TEXT,
    source_tier     TEXT
);
CREATE INDEX idx_lr_time ON log_records(timestamp);
CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);
```

New `LogPersistenceHandler(logging.Handler)` in `logging_.py`: accumulates records in a list, flushes to DB when batch reaches 50 records or 200ms elapses (whichever comes first). Filters by `log_persistence_level` (default INFO) before accumulating.

`LogPersistenceHandler` starts with `_db_service: DatabaseService | None = None` and `_loop: AbstractEventLoop | None = None`. Records are silently dropped (ring-buffered only) until `set_database(db_service, loop)` is called from `RuntimeQueryService.on_initialize()` (which already runs after `DatabaseService` is ready via `depends_on`). This mirrors the `LogCaptureHandler.set_broadcast()` late-wiring pattern. On flush, the handler serializes the batch to a plain data list and calls `loop.call_soon_threadsafe(lambda: db_service.enqueue(repository.insert_log_records(batch)))` — the handler runs in the QueueListener background thread and `asyncio.Queue.put_nowait()` is not thread-safe, so the `call_soon_threadsafe` crossing is required.

Add config fields to `HassetteConfig`:
- `log_retention_days: int = Field(default=3, ge=1)` — defaults to 3; a Pydantic validator constrains `log_retention_days <= db_retention_days` to prevent log records from outliving the invocation records that reference them
- `log_persistence_level: LOG_ANNOTATION = Field(default="INFO")` — minimum level for DB persistence
- `log_queue_max: int = Field(default=2000, ge=1)` — bounded queue size for the QueueHandler, matching `db_write_queue_max` convention

Extend `_do_run_retention_cleanup()` to delete from `log_records WHERE timestamp < cutoff` using `log_retention_days`. Extend `_check_size_failsafe()` with a dedicated pre-pass phase: exhaust the iteration budget deleting only from `log_records` (oldest-first) until the DB is under the size limit, then re-check size. Only if still over the limit does it enter the existing execution-record loop for `handler_invocations` and `job_executions`. This honors the "log records first" priority since they are the highest-volume, most-recoverable table.

**Repository methods** in `telemetry_repository.py`:
- `insert_log_records(records: list[dict])` — batch INSERT
- `get_log_records(limit, since, app_key, level, execution_id)` — paginated query with optional filters

**REST endpoints** — rewrite `GET /api/logs/recent` in `web/routes/logs.py` to query the DB instead of the in-memory buffer. Add `execution_id` query param. Keep the same response model shape but add `execution_id` and `source_tier` fields to `LogEntryResponse` in `web/models.py`.

Add `GET /api/logs/by-execution/{execution_id}` for direct per-invocation lookup. Include a `limit` parameter (default 500, max 5000), a `truncated: bool` field when the limit is hit, and a `retention_expired: bool` field when the query returns zero results and the execution's timestamp is older than `log_retention_days`. The frontend displays "Logs for this execution were deleted by retention policy" when `retention_expired=true`, distinguishing expired logs from executions that produced no output.

**Runtime log level endpoint** — add `PUT /api/logs/level` accepting `{"logger": "<name>", "level": "<DEBUG|INFO|WARNING|ERROR>"}`. Calls `logging.getLogger(name).setLevel(level)` — structlog wraps stdlib, so this takes effect immediately for both structlog and stdlib callers on that logger. Returns the logger's effective level. No UI toggle in this PR; the endpoint is usable via curl or API clients for live debugging.

**WebSocket broadcast** — `LogCaptureHandler` continues to broadcast live records with the new correlation fields included in the payload. No change to the WS protocol beyond the additional fields.

### Layer 5: Frontend

**LogTable modal interface** (`components/shared/log-table.tsx`):
- Add props: `fetcher` (custom fetch function), `mode: "live" | "historical"`, `useLocalState: boolean`
- In `historical` mode: use `fetcher` instead of `getRecentLogs`, skip WS merge, skip `updateLogSubscription`, use component-local state instead of URL query params
- In `live` mode (default): existing behavior (initial REST fetch + WS merge for live streaming), URL query params for filter/sort state

**Logs page** (`frontend/src/pages/logs.tsx`):
- Add `execution_id` URL query param support
- When `execution_id` is present: render `LogTable` in `historical` mode with a fetcher calling `GET /api/logs/by-execution/{id}`, show a "Viewing logs for execution {id}" banner with a clear-filter link
- When absent: render `LogTable` in `live` mode (existing behavior)
- Add `execution_id` column to the table (shown when not filtering by execution_id)
- Wire `useScopedApi` time-window preset to the REST fetch `since` parameter for historical log browsing

**App detail invocation logs** (`frontend/src/components/app-detail/handler-invocations.tsx`):
- In `InvocationDetail`, add a "Logs" section that lazy-fetches `GET /api/logs/by-execution/{execution_id}` on expand
- Render a full `LogTable` component pre-filtered to the execution_id, with sorting and level filtering
- The table fetches from the DB endpoint (no WS merge — these are historical records for a completed invocation)
- Handle empty state: "No logs recorded for this invocation"

**Schema regeneration**: After modifying `web/models.py`, regenerate OpenAPI spec and TypeScript types per the frontend-worktree workflow.

## Alternatives Considered

**Keep stdlib logging with custom Filter**: Instead of structlog, attach `logging.Filter` instances that stamp correlation IDs and format records. Pro: no new dependency. Con: loses the processor chain composability, dev/JSON renderer swap, and `foreign_pre_chain` for stdlib caller integration. The `coloredlogs` replacement would still need a separate solution. structlog is the standard choice for structured Python logging and provides all of these out of the box.

**Write logs to a separate file instead of SQLite**: Pro: simpler, no migration. Con: no indexing, no efficient per-execution queries, no retention integration with the existing DB infrastructure. The project already uses SQLite for telemetry; logs are a natural extension.

**Skip QueueHandler and keep synchronous logging**: Pro: simpler architecture. Con: log I/O blocks the event loop under load. The research identified this as a known anti-pattern for asyncio applications. stdlib's `QueueHandler` + `QueueListener` is a mechanical fix with zero library dependencies.

## Test Strategy

**Unit tests** for the new structlog wiring:
- Processor chain produces correct fields (execution_id, app_key, source_tier) for both structlog and stdlib log records
- `LogPersistenceHandler` batches correctly and respects the persistence level filter
- `LogCaptureHandler` includes correlation fields in entries
- Retention cleanup deletes log records by `log_retention_days`
- Size failsafe includes log_records

**Integration tests** for the log pipeline end-to-end:
- Emit a log during a handler execution via the harness → verify the record appears in the DB with correct execution_id
- Verify QueueHandler → QueueListener → handlers pipeline delivers to all three handlers
- Verify shutdown flushes all queued records

**E2E tests** for frontend:
- Log page displays historical records after page load
- Navigating to `/logs?execution_id=<id>` shows filtered results
- Expanding an invocation row shows log preview with "View all logs" link
- Clear-filter link returns to unfiltered view

**Existing test updates**:
- `tests/unit/test_logging.py` — rewrite for structlog-based `enable_logging()`
- `tests/e2e/test_logs.py` — extend for execution_id filtering and historical view

## Documentation Updates

- `docs/` logging guide: update to reflect structlog usage, new config fields (`log_format`, `log_retention_days`, `log_persistence_level`), and the per-invocation log view
- Docstrings on `enable_logging()`, `LogCaptureHandler`, `LogPersistenceHandler`, new config fields
- `CLAUDE.md` — no changes needed (logging architecture is not documented there)

## Impact

**Files modified:**
- `src/hassette/logging_.py` — major rewrite (structlog, QueueHandler, LogPersistenceHandler)
- `src/hassette/config/config.py` — add `log_format`, `log_retention_days`, `log_persistence_level`
- `src/hassette/core/database_service.py` — extend retention cleanup and size failsafe
- `src/hassette/core/telemetry_repository.py` — add log record insert/query methods
- `src/hassette/core/telemetry_models.py` — add log record Pydantic model
- `src/hassette/core/runtime_query_service.py` — update `get_recent_logs()` to query DB
- `src/hassette/web/routes/logs.py` — rewrite for DB-backed queries, add execution_id filter
- `src/hassette/web/models.py` — update `LogEntryResponse` with execution_id, instance_name, instance_index, source_tier
- `frontend/src/ws-types.ts` — add `execution_id`, `instance_name`, `instance_index`, `source_tier` to `WsLogPayload`
- `src/hassette/context.py` — no changes (CURRENT_EXECUTION_ID already exists)
- `src/hassette/core/command_executor.py` — no changes (execution_id already bound)
- `pyproject.toml` — add structlog, remove coloredlogs
- `frontend/src/components/shared/log-table.tsx` — execution_id filtering mode, historical support
- `frontend/src/pages/logs.tsx` — execution_id URL param
- `frontend/src/components/app-detail/handler-invocations.tsx` — inline log preview
- `frontend/src/api/endpoints.ts` — new log endpoints

**Files created:**
- `src/hassette/migrations/versions/009_log_records_table.py`

<!-- Gap check 2026-05-12: 16 gaps included — app_lifecycle_service.py:308 → T02 item 4, command_executor.py → T02 item 3, core.py:75,594 → T01 item 4 + T03 item 5, __main__.py:66 → T01 item 4, resources/base.py → T01 item 5, app/app.py → T01 item 5, test_logging.py → T01 item 8, e2e/conftest.py → T01 item 9, test_web_api.py → T01 item 9 + T05 item 11, test_runtime_query_service.py → T05 item 11, test_app_lifecycle_service.py → T01 item 9, web_mocks.py → T01 Focus, log-table.test.tsx → T06 item 7, create-app-state.ts → T05 item 8, overview-tab.tsx → T05 Focus, openapi.json+generated-types.ts → T05 item 9 -->

**Blast radius:** Moderate. The logging change touches every log record in the system, but structlog's stdlib wrapping means user code is unaffected. The DB change is additive (new table). The frontend changes extend existing components. The biggest risk is the QueueHandler shutdown ordering affecting WS broadcast reliability.

## Open Questions

None — all design decisions resolved during discovery.
