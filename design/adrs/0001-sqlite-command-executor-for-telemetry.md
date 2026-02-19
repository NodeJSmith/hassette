# ADR-0001: Use SQLite + Typed Command Executor for Operational Telemetry

## Status

Accepted

## Context

The web frontend needs persistent operational data — per-invocation handler records, job execution history across restarts, and session/uptime tracking. Today all this data lives in in-memory Python structures (`dict`, `deque`) that are lost on restart. The frontend can only show what's currently in RAM.

At the same time, `BusService._dispatch()` (~30 lines) and `SchedulerService.run_job()` (~45 lines) each own too many responsibilities: invoking the handler, timing it, recording metrics, catching and classifying exceptions, and logging errors. Adding database persistence directly into these methods would make them worse. The backlog also has an `on_error`/`on_exception` handler hook that would need to be wired into both services independently without a shared execution layer.

Key constraints:
- The codebase is async-first; `sqlite3` is synchronous (need `aiosqlite` or thread bridge)
- Python 3.11-3.13 supported; SQLite is bundled with Python (zero new system deps)
- Bus handlers fire on every Home Assistant state change (high write frequency, needs batching)
- All lifecycle management uses the `Resource`/`Service` system, not FastAPI lifespan
- `diskcache` (existing dependency) already uses SQLite under `data_dir`

Full analysis: [`design/research/2026-02-16-sqlite-command-pattern/research.md`](../research/2026-02-16-sqlite-command-pattern/research.md)

## Decision

Introduce two new services:

1. **`DatabaseService`** — manages a single SQLite database (`data_dir/hassette.db`) via `aiosqlite` with WAL mode. Runs schema migrations via Alembic (raw SQL, no SQLAlchemy). Tables: `handler_invocations`, `job_executions`, `sessions`.

2. **`CommandExecutor`** — a `Service` with a single public `execute(cmd)` method that accepts typed command dataclasses (`InvokeHandler`, `ExecuteJob`). It owns all cross-cutting execution concerns: timing, result recording, error classification, logging, error hooks, and queuing records for persistence. Its `serve()` loop drains a write queue in batches and persists to SQLite.

`BusService._dispatch()` and `SchedulerService.run_job()` delegate to the executor, reducing from ~30-45 lines of mixed concerns to ~5 lines of dispatch logic each. `DataSyncService` switches its read source from in-memory stores to DB queries (clean cutover, no transitional dual-read period).

## Consequences

**What becomes easier:**
- Operational data survives restarts — the frontend can show history, trends, and cross-session analytics
- Adding new cross-cutting concerns (error hooks, audit trails, new recording types) means modifying one class, not two services
- The `on_error`/`on_exception` backlog item fits naturally as `CommandExecutor._run_error_hooks()`
- Services are thinner and more focused: BusService on topic routing, SchedulerService on the heap queue
- Per-invocation handler records (new — bus currently only has aggregates) enable drill-down debugging

**What becomes harder or riskier:**
- Behavioral migration of `_dispatch()` exception handling — the current semantics are subtle (CancelledError propagates, DependencyError classified separately, others swallowed). Must be preserved exactly.
- Write queue introduces eventual consistency (~500ms) for persistence. Live WebSocket push can still use in-memory signals.
- Two new dependencies: `aiosqlite`, `alembic`
- New pattern for the codebase — developers must learn the Command Executor concept (mitigated by it being a single concrete class, not an abstract framework)
- Data retention policy needed to prevent unbounded DB growth

## Alternatives Considered

**Registered Command Bus** — Same as the chosen approach but with dynamic handler registration (`bus.register(InvokeHandler, handler_fn)`) instead of typed methods. More extensible (open/closed principle) but adds indirection and registration ceremony that isn't justified at 2-3 command types. If command types later proliferate, the typed methods can be promoted to a registration pattern without changing the data model or write infrastructure.

**Repository Pattern** — No executor. Add a `TelemetryRepository` protocol and call `await self.telemetry_repo.record(...)` from the existing service methods. Simplest mental model but **does not achieve the architectural goal** of thinning the services. `_dispatch()` would keep all its current responsibilities and gain a new one. The `on_error`/`on_exception` hook would still need to be wired into both services independently. Likely to be reworked later.
