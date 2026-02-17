# Research Brief: SQLite Database + Command Executor for Operational Telemetry

**Date**: 2026-02-16

**Status**: Ready for Decision

**Proposal**: Add a SQLite database for persistent operational telemetry and introduce a Command Executor that consolidates cross-cutting execution concerns (timing, recording, error handling) currently scattered across `BusService` and `SchedulerService`, making those services thinner in the process.

**Initiated by**: "Adding a SQLite database to power the frontend + using the Command pattern to avoid tight coupling of cross-domain actions"

## Context

### What prompted this

The web frontend (Jinja2 + HTMX) needs richer, persistent data. Today all operational data — listener metrics, job execution history, logs — lives in in-memory Python structures (`dict`, `deque`) that are lost on restart. The frontend can only show what's in RAM right now.

The specific data needed:
- **Per-invocation handler records**: timestamp, duration, success/failure, traceback for every bus event handler call
- **Job execution history** across restarts: same per-execution detail, surviving process lifecycle
- **Uptime / session tracking**: when the framework started, stopped, crashed
- **Future**: app configuration persistence, UI state/preferences

The architectural goal is equally important: `BusService._dispatch()` and `SchedulerService.run_job()` currently own too many responsibilities — invoking the handler, timing it, recording metrics, catching and classifying exceptions, logging errors. Adding database persistence on top of that would make them worse. The Command pattern should pull these cross-cutting concerns out of the services and into a dedicated execution layer, making the services thinner rather than fatter. This same executor would be the natural home for the `on_error`/`on_exception` handler hook that's in the backlog — instead of wiring error hooks into both `BusService` and `SchedulerService` independently, the executor handles it once.

### Current state

**Data stores (all in-memory, all lost on restart):**

| Store | Location | Type | Capacity |
|-------|----------|------|----------|
| Listener metrics | `BusService._listener_metrics` | `dict[int, ListenerMetrics]` | Unbounded (per listener) |
| Job execution log | `SchedulerService._execution_log` | `deque[JobExecutionRecord]` | Bounded ring buffer |
| Event buffer | `DataSyncService._event_buffer` | `deque[dict]` | Bounded ring buffer |
| Log buffer | `LogCaptureHandler._buffer` | `deque[LogEntry]` | Bounded (default 2000) |
| Entity state | `StateProxy.states` | `dict[str, HassStateDict]` | Unbounded (mirrors HA) |

**Current frontend data pipeline:**

```
BusService._listener_metrics ──┐
SchedulerService._execution_log─┤
StateProxy.states ──────────────┼── DataSyncService ── FastAPI routes ── Jinja2 templates
LogCaptureHandler._buffer ──────┤                                       ↕ HTMX partials
AppHandler registry ────────────┘                                       ↕ WebSocket push
```

`DataSyncService` is the sole aggregation layer between framework internals and the web tier. All routes inject it via `DataSyncDep`. It pulls data from the in-memory stores on each request.

**What `BusService._dispatch()` does today (~30 lines in `bus_service.py`):**

1. Get or create a `ListenerMetrics` object for this listener
2. Start a monotonic timer
3. Call `await listener.invoke(event)` (which runs DI injection → rate limiting → user handler)
4. On success: `metrics.record_success(duration_ms)`
5. On `DependencyError`: `metrics.record_di_failure(duration_ms, ...)`
6. On `HassetteError` or `Exception`: `metrics.record_error(duration_ms, ...)`, `self.logger.exception(...)`
7. On `CancelledError`: `metrics.record_cancelled(duration_ms)`, re-raise
8. If `listener.once`: remove the listener

**What `SchedulerService.run_job()` does today (~45 lines in `scheduler_service.py`):**

1. Resolve the callable (sync or async)
2. Use `track_execution()` context manager to time the call and capture errors
3. Call `await async_func(*job.args, **job.kwargs)`
4. On exception: `self.logger.exception(...)`
5. Build a `JobExecutionRecord` from the `ExecutionResult`
6. Append to `self._execution_log` deque

Both methods mix invocation, timing, error classification, metrics recording, and logging into one place. The Command Executor would own steps 1-2 and 4-6 (everything except the actual invocation target), letting the services focus on dispatch routing and job scheduling.

**Key observations:**
- `ListenerMetrics` only tracks **aggregates** (total success/fail counts, min/max timing). There are no per-invocation records for bus handlers — this gap must be filled for telemetry.
- `JobExecutionRecord` already has all the fields needed for a DB row (job_id, name, owner, started_at, duration_ms, status, error_type, error_message, error_traceback).
- `track_execution()` in `utils/execution.py` is a reusable async context manager that captures timing and error info — the executor would absorb or replace this.
- `diskcache` (already a dependency) uses SQLite internally, so the project already tolerates SQLite on disk under `data_dir`.
- The backlog has an `on_error`/`on_exception` handler feature. Today there's no single place to wire it — you'd have to add it to both `BusService._dispatch()` and `SchedulerService.run_job()`. The executor provides that single place.

**Existing persistence:**
- `Resource.cache` — a `diskcache.Cache` property on every `Resource` (lazy, disk-backed key/value store). Available to user apps but unused by framework core services. Uses SQLite under the hood.
- No other persistence. No database, no ORM, no migration tooling.

### Key constraints

- **Async-first**: The codebase is entirely async. `sqlite3` is synchronous. The established bridge pattern is `TaskBucket.run_in_thread()` or `asyncio.to_thread()`. `aiosqlite` is the conventional async wrapper.
- **Python 3.11-3.13**: All three versions supported. `aiosqlite` and stdlib `sqlite3` work across all.
- **Zero new system deps**: SQLite is bundled with Python — no external database server needed.
- **`filterwarnings = ["error"]` in pytest**: Currently set to catch missed `await` calls. Can be loosened for DB-specific warnings if needed — not a hard constraint.
- **FastAPI lifespan disabled**: `WebApiService` sets `lifespan="off"` — all lifecycle management goes through the Hassette `Resource`/`Service` system. Database open/close must use `on_initialize`/`on_shutdown`, not FastAPI's lifespan.
- **High write frequency**: Bus handlers fire frequently (every HA state change). Naive per-invocation INSERT would need batching or WAL mode to avoid contention.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| New `DatabaseService` | 1 new file + `core.py` wiring | Medium | Low — follows existing `Service` pattern |
| New `CommandExecutor` | 1-2 new files (executor + command types) | Medium | Medium — new pattern, but scoped to 2-3 methods |
| Slim down `BusService._dispatch()` | `bus_service.py` | Medium | Medium — hot path, behavioral change |
| Slim down `SchedulerService.run_job()` | `scheduler_service.py` | Low | Low — `JobExecutionRecord` already exists |
| `DataSyncService` read migration | `data_sync_service.py` | Medium | Medium — central aggregation layer |
| `ListenerMetrics` replacement/evolution | `bus/metrics.py` | Medium | Medium — aggregate metrics may be computed from DB |
| Schema / migrations | New `schema.sql` or migration files | Low | Low — greenfield |
| FastAPI DB dependency | `web/dependencies.py` | Low | Low |
| Config additions | `config/config.py` | Low | Low |
| Tests | 5-10 new test files | High | Low — follows existing patterns |
| Template changes | Minimal — existing templates work | Low | Low |

### What already supports this

- **`Service` base class** provides `on_initialize`/`on_shutdown` lifecycle hooks — perfect for `DatabaseService` and `CommandExecutor` (if it needs a write-batch loop).
- **`add_child()` + `wait_for_ready()`** wiring in `Hassette.__init__` handles startup ordering — new services slot in naturally.
- **`track_execution()`** context manager already captures timing and error info — the executor can absorb this or delegate to it.
- **`JobExecutionRecord`** dataclass has all fields needed for a DB row — no model redesign needed.
- **`HassetteConfig`** pydantic-settings pattern accommodates new fields (`db_path`, `db_wal_mode`, `run_db`).
- **`data-live-on-app`** HTMX attribute handles live partial refresh — telemetry dashboards would get real-time updates without new WebSocket wiring.
- **Existing `diskcache` dependency** means SQLite is already a tolerated presence in the data directory.
- **`DataSyncService`** is already the read aggregation layer — switching its data source from `dict`/`deque` to DB queries is localized.

### What works against this

- **`ListenerMetrics` is aggregate-only**: No per-invocation records exist for bus handlers. The executor must produce these — new data structure regardless of persistence approach.
- **`BusService._listener_metrics` dict is keyed by `listener_id`**: This is an auto-incrementing `int` that resets on restart. Persistent records need a stable identity (handler name + topic, or a UUID).
- **Behavioral change in `_dispatch()`**: Moving execution orchestration out of `_dispatch()` changes exception handling semantics. The core contract (handlers must not crash the bus) must be maintained, but the specific exception classification is worth auditing during the migration.
- **No migration tooling yet**: The project has no Alembic. Adding it is straightforward — Alembic supports raw SQL migrations without requiring SQLAlchemy models (plain `op.execute()` in upgrade/downgrade functions).
- **`diskcache` overlap**: Both `diskcache.Cache` and the new SQLite database write under `data_dir` — separate files, no conflict, but two persistence mechanisms to reason about.

## The Command Executor Pattern

### Core idea

The Command Executor is not a message bus or a persistence queue. It is the **execution layer** — it takes a command (what to run), runs it, and owns everything around that execution: timing, result recording, error classification, error hooks, and persistence. Services that currently orchestrate all of this themselves become thin dispatchers.

### What changes in the services

**`BusService._dispatch()` today** (~30 lines, mixed concerns):

```python
async def _dispatch(self, topic, event, listener):
    metrics = self._get_or_create_metrics(listener)
    started = time.monotonic()
    try:
        await listener.invoke(event)
        duration = (time.monotonic() - started) * 1000
        metrics.record_success(duration)
    except asyncio.CancelledError:
        metrics.record_cancelled(...)
        raise
    except DependencyError as e:
        metrics.record_di_failure(...)
        self.logger.error(...)
    except HassetteError as e:
        metrics.record_error(...)
        self.logger.error(...)
    except Exception as e:
        metrics.record_error(...)
        self.logger.exception(...)
    finally:
        if listener.once:
            self.remove_listener(listener)
```

**`BusService._dispatch()` after** (~5 lines):

```python
async def _dispatch(self, topic, event, listener):
    cmd = InvokeHandler(listener=listener, event=event, topic=topic)
    await self._executor.execute(cmd)
    if listener.once:
        self.remove_listener(listener)
```

**`SchedulerService.run_job()` today** (~45 lines):

```python
async def run_job(self, job):
    async_func = self._resolve_callable(job)
    result = ExecutionResult()
    try:
        async with track_execution() as result:
            await async_func(*job.args, **job.kwargs)
    except asyncio.CancelledError:
        raise
    except Exception:
        self.logger.exception("Error running job %s", job)
    finally:
        record = JobExecutionRecord(
            job_id=job.job_id, job_name=job.name, owner=job.owner,
            started_at=timestamp, duration_ms=result.duration_ms,
            status=result.status, error_message=result.error_message,
            error_type=result.error_type, error_traceback=result.error_traceback,
        )
        self._execution_log.append(record)
```

**`SchedulerService.run_job()` after** (~5 lines):

```python
async def run_job(self, job):
    cmd = ExecuteJob(job=job, callable=self._resolve_callable(job))
    await self._executor.execute(cmd)
```

### The executor itself

```python
@dataclass(frozen=True)
class InvokeHandler:
    listener: Listener
    event: Event
    topic: str

@dataclass(frozen=True)
class ExecuteJob:
    job: ScheduledJob
    callable: AsyncHandlerType

class CommandExecutor(Service):
    """Owns cross-cutting execution concerns: timing, recording, error hooks, persistence."""

    _write_queue: asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord]

    async def execute(self, cmd: InvokeHandler | ExecuteJob) -> None:
        """Single entry point. Dispatches internally based on command type."""
        match cmd:
            case InvokeHandler():
                await self._execute_handler(cmd)
            case ExecuteJob():
                await self._execute_job(cmd)

    async def _execute_handler(self, cmd: InvokeHandler) -> None:
        """Invoke an event handler and record the result."""
        started = time.monotonic()
        try:
            await cmd.listener.invoke(cmd.event)
            duration_ms = (time.monotonic() - started) * 1000
            record = HandlerInvocationRecord(
                ..., status="success", duration_ms=duration_ms,
            )
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - started) * 1000
            record = HandlerInvocationRecord(..., status="cancelled", ...)
            raise  # CancelledError must propagate
        except Exception as e:
            duration_ms = (time.monotonic() - started) * 1000
            record = HandlerInvocationRecord(
                ..., status="error", error_type=type(e).__name__,
                error_message=str(e), error_traceback=traceback.format_exc(),
            )
            await self._run_error_hooks(e, cmd)  # on_error/on_exception from backlog
            self.logger.exception("Handler error: %s", cmd.listener.handler_name)
        finally:
            self._write_queue.put_nowait(record)

    async def _execute_job(self, cmd: ExecuteJob) -> None:
        """Execute a scheduled job and record the result."""
        started = time.monotonic()
        try:
            await cmd.callable(*cmd.job.args, **cmd.job.kwargs)
            duration_ms = (time.monotonic() - started) * 1000
            record = JobExecutionRecord(..., status="success", ...)
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - started) * 1000
            record = JobExecutionRecord(..., status="cancelled", ...)
            raise
        except Exception as e:
            duration_ms = (time.monotonic() - started) * 1000
            record = JobExecutionRecord(
                ..., status="error", error_traceback=traceback.format_exc(), ...
            )
            await self._run_error_hooks(e, cmd)
            self.logger.exception("Job error: %s", cmd.job.name)
        finally:
            self._write_queue.put_nowait(record)

    async def _run_error_hooks(self, exc: Exception, cmd: InvokeHandler | ExecuteJob) -> None:
        """Run registered on_error/on_exception hooks. Backlog item gets wired here."""
        for hook in self._error_hooks:
            try:
                await hook(exc, cmd)
            except Exception:
                self.logger.exception("Error hook failed")

    async def serve(self) -> None:
        """Drain write queue in batches and persist to SQLite."""
        while True:
            batch = await self._drain_queue(max_size=100, timeout_seconds=0.5)
            async with self._db.transaction():
                for record in batch:
                    await self._persist(record)
```

### What this gives you

- **Services get thinner**: `BusService` focuses on topic routing and listener management. `SchedulerService` focuses on the heap queue and rescheduling. Neither knows about timing, metrics, DB, or error hooks.
- **Single place for cross-cutting concerns**: Timing, result recording, error classification, logging, persistence, and error hooks all live in `CommandExecutor`. Adding a new concern means modifying one class, not two services.
- **`on_error`/`on_exception` hooks**: The backlog item drops in naturally as `_run_error_hooks()`. No need to wire it into multiple services.
- **Per-invocation records**: Every handler call and job execution produces a typed record (dataclass), which gets queued for DB persistence. The aggregate `ListenerMetrics` can be computed from these records or maintained in parallel.
- **Testability**: Commands are frozen dataclasses. The executor can be tested with mock listeners/jobs. Error hook behavior is testable in isolation.

## Options Evaluated

### Option A: Typed Command Executor (Recommended)

**How it works:**

As described above. A `CommandExecutor(Service)` with a single public `execute(cmd)` method that dispatches internally based on command type. A `DatabaseService(Service)` manages the SQLite connection (WAL mode, via `aiosqlite`). Schema migrations managed by Alembic with raw SQL (no SQLAlchemy models). The executor's `serve()` loop drains a write queue in batches and persists to SQLite. `DataSyncService` reads switch directly from in-memory stores to DB queries (clean cutover, no transitional period).

Commands are frozen dataclasses that encapsulate the inputs to an execution (listener + event, or job + callable). Services call `self._executor.execute(cmd)` — they don't need to know which internal method handles their command type. The executor runs the action, captures the result, fires error hooks, and queues the record for persistence.

**Pros:**
- Services get dramatically thinner — `_dispatch()` and `run_job()` go from ~30-45 lines to ~5
- Single `execute(cmd)` entry point — services don't know or care about internal dispatch
- Cross-cutting concerns consolidated: timing, recording, error hooks, persistence, logging — one place
- `on_error`/`on_exception` backlog item fits naturally as a hook on the executor
- Per-invocation records for both bus and scheduler, persisted to SQLite
- Write batching (queue → batch INSERT in transaction) gives high throughput without per-event overhead
- Internal `match` dispatch means no registration machinery — just add a case for new command types
- Follows the existing `Service` pattern — has `on_initialize`, `on_shutdown`, `serve()` loop
- Evolution path: if command types proliferate, promote to registered handlers later

**Cons:**
- Exception handling semantics need review: the current `_dispatch()` handling is subtle (CancelledError propagates, others are swallowed, DependencyError classified separately). The migration is an opportunity to audit whether these semantics are correct, not just replicate them. With a small userbase, now is the right time to fix any questionable error handling rather than carry it forward.
- Write queue introduces eventual consistency for persistence — a handler invocation may not appear in the DB for up to 500ms. Live WebSocket push can still use in-memory signals.
- Adding a new command type requires adding a `match` case and a private method (acceptable at 2-3 types, less so at 10+).
- New pattern for the codebase — `CommandExecutor` is a concept developers must learn. Mitigated by it being a single concrete class with typed methods, not an abstract framework.

**Effort estimate:** Large — new service, behavioral migration of two hot-path methods, schema design, per-invocation recording for bus (new), test infrastructure. But the effort is front-loaded; once the executor exists, adding concerns (error hooks, new recording types) is cheap.

**Dependencies:** `aiosqlite`, `alembic`

### Option B: Registered Command Bus (more extensible, more indirection)

**How it works:**

Same as Option A, but instead of typed methods, the executor dispatches commands to registered handlers based on type:

```python
class CommandBus(Service):
    _handlers: dict[type, Callable]

    def register(self, command_type: type, handler: Callable) -> None: ...

    async def execute(self, command: Command) -> None:
        handler = self._handlers[type(command)]
        await handler(command)
```

Each command type gets a handler registered at startup. The cross-cutting concerns (timing, recording, error hooks) are either in each handler (duplicated) or implemented as middleware/decorators wrapping each handler.

**Pros:**
- Most extensible — new command type = new registration, no executor modification
- Open/closed principle — the bus itself never changes
- Familiar pattern if coming from CQRS frameworks

**Cons:**
- Cross-cutting concerns either get duplicated per handler or require a middleware abstraction — which is essentially what Option A's typed methods already are, just more explicit
- More indirection: `execute(cmd)` → handler lookup → handler function → middleware → actual execution
- Registration ceremony at startup adds wiring code
- Overkill for 2-3 command types — the machinery exists to solve a problem you don't have yet

**Effort estimate:** Large — same as Option A plus registration infrastructure and middleware pattern

**Dependencies:** `aiosqlite`

### Option C: Repository Pattern (simpler, does not slim the services)

**How it works:**

No executor. Define a `TelemetryRepository` protocol. `BusService._dispatch()` and `SchedulerService.run_job()` keep their current structure but add `await self.telemetry_repo.record(...)` calls after execution. `DataSyncService` reads from the repository.

```python
class TelemetryRepository(Protocol):
    async def record_handler_invocation(self, record: HandlerInvocationRecord) -> None: ...
    async def record_job_execution(self, record: JobExecutionRecord) -> None: ...
    async def get_handler_history(self, listener_id: str, limit: int) -> list[HandlerInvocationRecord]: ...
    async def get_job_history(self, owner: str | None, limit: int) -> list[JobExecutionRecord]: ...
```

**Pros:**
- Simplest mental model — repositories are widely understood
- Direct async/await — no write queue, no eventual consistency
- Protocols match existing codebase conventions

**Cons:**
- **Does not make services thinner** — `BusService._dispatch()` keeps all its current responsibilities and gains a new one (repository call). This is the opposite of the stated goal.
- No write batching — each invocation is a separate INSERT (slower)
- `on_error`/`on_exception` hooks still need to be wired into both services independently
- `_dispatch()` becomes async-dependent on DB availability — if DB is slow, event dispatch slows down
- To add batching later, you'd reinvent the write queue from Option A

**Effort estimate:** Medium — but doesn't achieve the architectural goal and would likely be reworked later

**Dependencies:** `aiosqlite`

## Concerns

### Technical risks

- **Behavioral migration of `_dispatch()`**: The exception handling in `BusService._dispatch()` is subtle. `CancelledError` must propagate (re-raised). `DependencyError` is classified differently from general `Exception`. The executor must preserve these exact semantics — this needs thorough testing with the existing bus integration tests.
- **Bus dispatch hot path**: `_dispatch()` fires on every HA state change. The executor adds a method call and a `queue.put_nowait()`. This is O(1) but measurable at high event rates (100+ events/second). Benchmark with realistic loads.
- **SQLite write throughput**: WAL mode with batched transactions handles 50k+ inserts/second. The concern is not raw throughput but ensuring the write queue doesn't back up during event bursts. A bounded queue with backpressure (drop oldest or log warning) is needed.
- **Stable listener identity**: `listener_id` is currently an auto-incrementing `int` that resets on restart. Persistent records need a stable key — `f"{owner}:{handler_name}:{topic_pattern}"` or similar. This is a design decision for the schema, not a blocker.
- **WAL file growth**: High-frequency writes can cause the WAL file to grow indefinitely if checkpoints are blocked by long-running reads. Set `PRAGMA wal_autocheckpoint` and optionally run periodic `PRAGMA wal_checkpoint(TRUNCATE)`.

### Complexity risks

- **Clean cutover, not gradual migration**: The in-memory stores get replaced by the DB in one pass — no transitional period with two read paths. This is simpler but means the cutover PR must be thorough. Small userbase makes this the right call.
- **Test infrastructure**: Database tests need fixtures for schema setup/teardown, in-memory vs. on-disk strategies for speed, and isolation under `pytest-xdist` parallel workers.

### Maintenance risks

- **Data retention**: Per-invocation records accumulate indefinitely. Need a retention policy (e.g., `DELETE WHERE timestamp < datetime('now', '-7 days')`) run periodically in the executor's `serve()` loop, or the DB file grows without bound.
- **Executor as a God object**: If every cross-cutting concern gets added to the executor (logging, metrics, DB writes, error hooks, audit trails...), it becomes the new monolith. Keep it focused on execution recording + error hooks. Concerns like structured logging or audit trails should be separate services that consume the same records.

## Open Questions

- [ ] Should `aiosqlite` be the async bridge, or should we wrap `sqlite3` in `run_in_thread` to stay consistent with how `diskcache` is used? (`aiosqlite` is more idiomatic but adds a dependency; `run_in_thread` reuses the existing pattern.)
- [ ] What retention policy for per-invocation records? 7 days? 30 days? Configurable? Size-based (e.g., max 1M rows)?
- [ ] Should the DB file live at `data_dir/hassette.db` (single file, room for future tables) or `data_dir/telemetry.db` (scoped to this concern)?
- [ ] Alembic configuration: should migrations live under `src/hassette/migrations/` (shipped with the package) or at the project root? Alembic with raw SQL (no SQLAlchemy models) is the plan — just need to decide on the directory layout.
- [ ] Should aggregate `ListenerMetrics` be kept in parallel (fast reads for live dashboard) or computed on-demand from per-invocation DB records (simpler, but slower for aggregate queries)?
- [ ] Should the `diskcache.Cache` on `Resource` be replaced by the new DB, or kept as a separate concern? (They serve different purposes: diskcache is per-resource key/value, the new DB is framework-wide telemetry.)
- [ ] What `DependencyError` classification means for the executor — should DI failures be a distinct status in the DB schema, or just another error type?

## Recommendation

**Go with Option A (Typed Command Executor).**

It directly addresses both goals:

1. **Persistent telemetry** — per-invocation records for bus handlers and job executions, persisted to SQLite via batched writes, queryable by the frontend for history, filtering, and drill-down.
2. **Thinner services** — `BusService._dispatch()` and `SchedulerService.run_job()` shed their cross-cutting concerns (timing, metrics, error classification, logging) to the executor. They become thin dispatchers focused on their core responsibility (topic routing, job scheduling).
3. **Error hook extensibility** — the `on_error`/`on_exception` backlog item fits naturally as `CommandExecutor._run_error_hooks()`, wired once instead of twice.

Option B (Registered Command Bus) offers more extensibility but adds indirection that isn't justified at 2-3 command types. If command types later proliferate, Option A's typed methods can be promoted to a registration pattern — the data model and write infrastructure transfer directly.

Option C (Repository) doesn't achieve the architectural goal of thinning the services. It adds DB calls to already-complex methods.

### Suggested next steps

1. **Record the decision** — create an ADR capturing the choice of SQLite + Typed Command Executor (`/mine.adrs`)
2. **Design the schema** — define tables for `handler_invocations`, `job_executions`, `sessions`, with indexes, retention columns, and the stable listener identity scheme
3. **Set up Alembic** — configure with raw SQL migrations (no SQLAlchemy models), decide on migration directory layout
4. **Implement in 1-2 PRs** (clean cutover, no transitional period):
   - `DatabaseService` + Alembic + initial schema
   - `CommandExecutor` with `execute()` dispatching to `_execute_job()` and `_execute_handler()`
   - Migrate `SchedulerService.run_job()` and `BusService._dispatch()` to use the executor
   - Switch `DataSyncService` reads from in-memory stores to DB queries
   - Add `HandlerInvocationRecord` (new — bus currently only has aggregates)
   - Remove replaced in-memory stores (`_listener_metrics`, `_execution_log`)
5. **Follow-up PR(s)**: Wire `on_error`/`on_exception` hooks, session/uptime tracking, retention policy, dashboard enhancements

## Sources

- [aiosqlite: asyncio bridge to sqlite3](https://github.com/omnilib/aiosqlite)
- [aiosqlite performance discussion](https://github.com/omnilib/aiosqlite/issues/97)
- [Going Fast with SQLite and Python — Charles Leifer](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/)
- [SQLite WAL mode documentation](https://sqlite.org/wal.html)
- [SQLite performance tuning — phiresky](https://phiresky.github.io/blog/2020/sqlite-performance-tuning/)
- [SQLite optimizations for ultra high-performance — PowerSync](https://www.powersync.com/blog/sqlite-optimizations-for-ultra-high-performance)
- [CQRS chapter — Architecture Patterns with Python (Cosmic Python)](https://www.cosmicpython.com/book/chapter_12_cqrs.html)
- [CQRS Pattern in Python — OneUptime](https://oneuptime.com/blog/post/2026-01-22-cqrs-pattern-python/view)
