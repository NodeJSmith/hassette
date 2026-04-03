# Design: CommandExecutor — Issue #266

**Status:** archived

**Date**: 2026-03-11
**Status**: implemented
**Milestone**: SQLite + Command Executor
**ADR**: [ADR-0001](../../adrs/0001-sqlite-command-executor-for-telemetry.md)
**Research**: [design/research/2026-02-16-sqlite-command-pattern/](../../research/2026-02-16-sqlite-command-pattern/)

---

## Problem

`BusService._dispatch()` (~30 lines) and `SchedulerService.run_job()` (~45 lines) each own too many responsibilities: invoking the handler/job, timing it, recording metrics, catching and classifying exceptions, and logging errors. The result is two methods that are hard to test and will only grow worse as features are added (error hooks, new recording types).

The `DatabaseService` is in place (PR #305). The schema is ready. The missing piece is the **execution layer** — a `CommandExecutor(Service)` that consolidates cross-cutting concerns and delegates to `DatabaseService` for persistence.

Additionally:
- Bus handlers have **no per-invocation records** — only in-memory aggregate `ListenerMetrics`. The frontend can't show per-invocation history or drill-down.
- Job execution history lives in a bounded in-memory `deque` lost on restart. The frontend shows only what's in RAM right now.

---

## Scope

**This issue (#266)** implements the execution layer and migrates the two services. It does **not** migrate `DataSyncService` to read from the DB — that is #267.

**Included:**
- `CommandExecutor(Service)` — timing, recording, error classification, logging, write queue
- `HandlerInvocationRecord` dataclass (new)
- Modernized `JobExecutionRecord` — `Instant` timestamps, FK-based identity, `frozen=True`
- `ListenerRegistration` and `ScheduledJobRegistration` dataclasses (parent table records)
- `capture_registration_source()` utility (AST-based, per-file cached)
- `safe_json_serialize()` utility
- Parent table upsert on listener/job registration
- `BusService._dispatch()` → ~5 lines (delegates to executor)
- `SchedulerService.run_job()` → ~5 lines (delegates to executor)
- Remove `BusService._listener_metrics` dict and `ListenerMetrics` usage
- Remove `SchedulerService._execution_log` deque
- Stub `DataSyncService` methods that read from removed stores (return empty until #267)
- Tests: executor exception contract, write queue batching, parent table upsert, source capture

**Not included:**
- DataSyncService decomposition (#267)
- Error hooks wiring (`_run_error_hooks()` stub only, #268)
- New UI views (#268)
- Retention policy (already in `DatabaseService.serve()`)

---

## Architecture

### New files

| File | Purpose |
|------|---------|
| `src/hassette/core/command_executor.py` | `CommandExecutor(Service)` — single execute entry point |
| `src/hassette/core/commands.py` | `InvokeHandler`, `ExecuteJob` frozen command dataclasses |
| `src/hassette/core/registration.py` | `ListenerRegistration`, `ScheduledJobRegistration` frozen dataclasses |
| `src/hassette/utils/source_capture.py` | `capture_registration_source()` — AST-based, per-file cached |
| `src/hassette/utils/serialization.py` | `safe_json_serialize()` |
| `tests/integration/test_command_executor.py` | Executor integration tests |
| `tests/unit/core/test_source_capture.py` | Source capture unit tests |

### Changed files

| File | Change |
|------|--------|
| `src/hassette/core/core.py` | Add `_command_executor`, wire into BusService and SchedulerService |
| `src/hassette/core/bus_service.py` | Accept `executor` arg, slim `_dispatch()`, remove `_listener_metrics`, upsert on add_listener |
| `src/hassette/core/scheduler_service.py` | Accept `executor` arg, slim `run_job()`, remove `_execution_log`, upsert on job registration |
| `src/hassette/core/data_sync_service.py` | Stub out methods reading `_listener_metrics` / `_execution_log` |
| `src/hassette/scheduler/classes.py` | Modernize `JobExecutionRecord`, add `HandlerInvocationRecord` |
| `src/hassette/bus/metrics.py` | Remove `ListenerMetrics` (or keep as deprecated, remove imports from bus_service) |

### Removed items

- `BusService._listener_metrics: dict[int, ListenerMetrics]`
- `BusService._get_or_create_metrics()`
- `BusService.get_all_listener_metrics()`
- `BusService.get_listener_metrics_by_owner()`
- `SchedulerService._execution_log: deque[JobExecutionRecord]`
- `SchedulerService.get_execution_log()` (if it exists)

---

## CommandExecutor

### Location

`src/hassette/core/command_executor.py`

### Class structure

```python
class CommandExecutor(Service):
    """Owns cross-cutting execution concerns: timing, recording, error classification,
    logging, and batched persistence to SQLite.
    """

    _write_queue: asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord]
    _session_id: int  # set on on_initialize, stamped on every record

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue()

    async def on_initialize(self) -> None:
        self._session_id = self.hassette.session_id

    async def execute(self, cmd: InvokeHandler | ExecuteJob) -> None:
        """Single public entry point. Dispatches internally based on command type."""
        match cmd:
            case InvokeHandler():
                await self._execute_handler(cmd)
            case ExecuteJob():
                await self._execute_job(cmd)

    async def serve(self) -> None:
        """Drain write queue in batches and persist to SQLite."""
        self.mark_ready(reason="CommandExecutor started")
        while True:
            # Wait for first item or shutdown
            done, _ = await asyncio.wait(
                [
                    asyncio.ensure_future(self._write_queue.get()),
                    asyncio.ensure_future(self.shutdown_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self.shutdown_event.is_set():
                await self._flush_queue()
                return
            await self._drain_and_persist()

    async def register_listener(self, registration: ListenerRegistration) -> int:
        """Upsert a listener into the parent table. Returns the row id."""
        ...

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Upsert a scheduled job into the parent table. Returns the row id."""
        ...
```

### Exception contract

Mirrors the decisions from [prereq-03](../../research/2026-02-16-sqlite-command-pattern/prereq-03-exception-handling-audit.md):

```
CancelledError   → record status="cancelled" → queue record → RE-RAISE
DependencyError  → record status="error", error_type="DependencyError" → logger.error() → SWALLOW
HassetteError    → record status="error" → logger.error() (clean, no traceback) → SWALLOW
Exception        → record status="error" → logger.exception() (with traceback) → SWALLOW
```

The distinction between `HassetteError` and `Exception` is preserved: framework errors use `logger.error()` (clean message), unexpected errors use `logger.exception()` (full traceback).

### Write queue

- `asyncio.Queue()` — unbounded (bus handlers fire on every HA state change; bounded queue risks `put_nowait` drops under bursts. Monitor queue size via logging if needed.)
- `serve()` drains up to 100 records per batch cycle, 500ms timeout between batches
- All records in a batch are written in a single transaction: `async with db.executemany()`
- On shutdown, `_flush_queue()` drains remaining records before returning
- `_run_error_hooks()` stub in place; hook registration is #268

### Timing

The executor owns timing directly (not via `track_execution()`). `track_execution()` re-raises all exceptions, which conflicts with the executor's swallow behavior. The executor captures:
- `execution_start_ts: Instant = Instant.now()` — wall-clock, before invocation
- `_mono_start: float = time.monotonic()` — for duration calculation
- `duration_ms: float = (time.monotonic() - _mono_start) * 1000` — in `finally`

---

## Data Model

### Command dataclasses

`src/hassette/core/commands.py`:

```python
@dataclass(frozen=True)
class InvokeHandler:
    listener: "Listener"
    event: "Event[Any]"
    topic: str
    listener_id: int  # FK to listeners table, set when listener is registered

@dataclass(frozen=True)
class ExecuteJob:
    job: "ScheduledJob"
    callable: "AsyncHandlerType"
    job_db_id: int  # FK to scheduled_jobs table, set when job is registered
```

### HandlerInvocationRecord

Add to `src/hassette/bus/` (new file or alongside existing):

```python
@dataclass(frozen=True)
class HandlerInvocationRecord:
    listener_id: int          # FK to listeners table
    session_id: int           # FK to sessions table
    execution_start_ts: float # Instant epoch seconds (UTC)
    duration_ms: float
    status: str               # "success", "error", "cancelled"
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
```

### JobExecutionRecord (modernized)

`src/hassette/scheduler/classes.py` — update existing dataclass:

| Field | Before | After |
|-------|--------|-------|
| `job_id` | `int` (process-local) | `int` (FK to `scheduled_jobs` table) |
| `job_name` | `str` | removed (lives on parent table) |
| `owner` | `str` (opaque) | removed (lives on parent table) |
| `started_at` | `float` (`time.time()`) | `execution_start_ts: float` (Instant epoch) |
| `frozen` | no | yes (`@dataclass(frozen=True)`) |
| `session_id` | absent | `int` (FK to sessions table) |

### Parent table registration dataclasses

`src/hassette/core/registration.py`:

```python
@dataclass(frozen=True)
class ListenerRegistration:
    app_key: str
    instance_index: int
    handler_method: str
    topic: str
    debounce: float | None
    throttle: float | None
    once: bool
    priority: int
    predicate_description: str | None
    source_location: str
    registration_source: str | None
    first_registered_at: float  # Instant epoch seconds
    last_registered_at: float   # Instant epoch seconds

@dataclass(frozen=True)
class ScheduledJobRegistration:
    app_key: str
    instance_index: int
    job_name: str
    handler_method: str
    trigger_type: str | None    # "cron", "interval", or None (one-shot)
    trigger_value: str | None
    repeat: bool
    args_json: str
    kwargs_json: str
    source_location: str
    registration_source: str | None
    first_registered_at: float  # Instant epoch seconds
    last_registered_at: float   # Instant epoch seconds
```

---

## BusService Migration

### Constructor change

```python
def __init__(
    self,
    hassette: "Hassette",
    *,
    stream: "MemoryObjectReceiveStream[...]",
    executor: "CommandExecutor",
    parent: "Resource | None" = None,
) -> None:
    super().__init__(hassette, parent=parent)
    self.stream = stream
    self._executor = executor
    # _listener_metrics REMOVED
```

### _dispatch() after

```python
async def _dispatch(self, topic: str, event: "Event[Any]", listener: "Listener") -> None:
    cmd = InvokeHandler(
        listener=listener, event=event, topic=topic,
        listener_id=listener.db_id,  # set during registration
    )
    await self._executor.execute(cmd)
    if listener.once:
        self.remove_listener(listener)
```

### Listener registration

When `add_listener()` is called (during App.on_initialize), build a `ListenerRegistration` and call `await self._executor.register_listener(reg)`. Store the returned DB id on the `Listener` object as `listener.db_id`. This `db_id` is then passed in `InvokeHandler`.

### Removed from BusService

- `_listener_metrics: dict[int, ListenerMetrics]`
- `_get_or_create_metrics()`
- `get_all_listener_metrics()` → returns `[]` (stub for DataSyncService until #267)
- `get_listener_metrics_by_owner()` → returns `[]` (stub for DataSyncService until #267)

---

## SchedulerService Migration

### Constructor change

```python
def __init__(self, hassette: "Hassette", *, executor: "CommandExecutor", parent: Resource | None = None) -> None:
    super().__init__(hassette, parent=parent)
    self._executor = executor
    # _execution_log REMOVED
```

### run_job() after

```python
async def run_job(self, job: "ScheduledJob") -> None:
    if job.cancelled:
        self.logger.debug("Job %s is cancelled, skipping", job)
        await self._remove_job(job)
        return

    run_at_delta = job.next_run - now()
    if run_at_delta.in_seconds() < -self.hassette.config.scheduler_behind_schedule_threshold_seconds:
        self.logger.warning("Job %s is behind schedule by %s seconds, running now.", job, abs(run_at_delta.in_seconds()))

    cmd = ExecuteJob(job=job, callable=self.task_bucket.make_async_adapter(job.job), job_db_id=job.db_id)
    await self._executor.execute(cmd)
```

### Job registration

When a `ScheduledJob` is first added to the queue, call `await self._executor.register_job(reg)` and store the returned id on `job.db_id`. This can happen in `_add_job()` or wherever jobs enter the queue from the user-facing `Scheduler`.

### Removed from SchedulerService

- `_execution_log: deque[JobExecutionRecord]`
- Any `get_execution_log()` accessor → returns `[]` (stub until #267)

---

## Hassette Wiring

In `Hassette.__init__()`:

```python
self._database_service = self.add_child(DatabaseService)
self._command_executor = self.add_child(CommandExecutor)  # NEW — after DB, before bus/scheduler
self._bus_service = self.add_child(BusService, stream=self._receive_stream.clone(), executor=self._command_executor)
...
self._scheduler_service = self.add_child(SchedulerService, executor=self._command_executor)
```

Expose on `Hassette`:

```python
@property
def command_executor(self) -> CommandExecutor:
    """CommandExecutor for telemetry recording."""
    return self._command_executor
```

CommandExecutor's `on_initialize()` must wait for `DatabaseService` to be ready before it can use the DB connection. Use `await self.hassette.wait_for_ready([self.hassette.database_service])`.

---

## DataSyncService Stubs

Methods that currently read from `_listener_metrics` or `_execution_log` return empty data until #267 migrates them to DB queries:

```python
# Stub — returns empty until #267 migrates to TelemetryQueryService
def get_bus_metrics_summary(self) -> BusMetricsSummaryResponse:
    return BusMetricsSummaryResponse(listeners=[])

# Removed — SchedulerSummaryResponse was replaced by
# TelemetryQueryService per-app job queries (#267, wave 4).
```

Add a `# TODO(#267)` comment on each stub so they're easy to find during #267.

---

## Utilities

### capture_registration_source()

`src/hassette/utils/source_capture.py`:

- Uses `inspect.stack()` to get the caller's filename + line number (walk up the stack past Bus/Scheduler internals to the app frame)
- Uses `ast.parse()` to find the `Call` node at that line — `ast.get_source_segment(source, node)`
- Per-file caching: `dict[str, ast.Module]` — parse once per file, reuse on subsequent registrations from the same file
- Returns `(source_location: str, registration_source: str | None)` — `None` if capture fails (REPL, exec, no source available)
- Never runs on the hot path (registration-time only)

### safe_json_serialize()

`src/hassette/utils/serialization.py`:

```python
def safe_json_serialize(value: Any) -> str:
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return '"<NON_SERIALIZABLE>"'
```

---

## Testing

### Executor exception contract (`tests/integration/test_command_executor.py`)

Test each exception path in isolation using a mock listener/job that raises the target exception:

- `CancelledError` → record queued with `status="cancelled"`, error re-raised
- `DependencyError` → record queued with `status="error"`, `error_type="DependencyError"`, `logger.error` called (not `logger.exception`)
- `HassetteError` → record queued with `status="error"`, `logger.error` called (no traceback)
- `Exception` → record queued with `status="error"`, `logger.exception` called (traceback)
- Success → record queued with `status="success"`, no error fields

### Write queue batching

- Verify records queued via `put_nowait` are flushed in batches to the DB
- Verify batch limit (100 records) is respected
- Verify records present in DB after `serve()` drains the queue
- Verify `_flush_queue()` on shutdown persists remaining records

### Parent table upsert

- Register same listener twice → one row in `listeners` table, `last_registered_at` updated
- Register new listener → new row
- Same for `scheduled_jobs`
- Verify `first_registered_at` NOT overwritten on second upsert

### Source capture (`tests/unit/core/test_source_capture.py`)

- Happy path: registration call source extracted correctly
- Per-file cache: source file parsed once for multiple registrations from same file
- REPL / no source → `registration_source = None`, `source_location` still captured from frame
- Lambda / partial callable → graceful fallback

### Behavioral equivalence

Existing bus integration tests (`tests/integration/test_bus*.py`) and scheduler tests must pass after migration with no changes needed. This is the primary regression check.

---

## Alternatives Considered

See ADR-0001 and research brief. The decision is settled: Typed Command Executor (Option A).

The one design variation within #266 scope: keeping `_listener_metrics` in parallel vs. clean cutover. **Clean cutover chosen** — `_listener_metrics` and `_execution_log` are removed. DataSyncService returns empty stubs until #267. This avoids awkward coupling between the executor and the metrics dict, achieves the stated goal of `_dispatch()` → ~5 lines, and avoids maintaining two sources of truth.
