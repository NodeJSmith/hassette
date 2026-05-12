# Context: Logging Overhaul

## Problem & Motivation
Hassette's logging has three critical gaps: concurrent handler logs interleave without correlation IDs making live debugging unreliable, all logs are lost on restart making post-incident investigation impossible, and the console output library (coloredlogs) is unmaintained and broken on Python 3.13+. This overhaul replaces coloredlogs with structlog, adds ContextVar-based correlation IDs at handler dispatch, moves log I/O off the event loop via QueueHandler, persists log records to SQLite, and adds per-invocation log views in the frontend.

## Key Decisions
1. structlog wraps stdlib logging via ProcessorFormatter — existing `logging.getLogger()` calls in user apps continue to work without changes.
2. `source_tier` is a structlog bound variable on each logger instance (not a context var) — prevents tier leakage during concurrent execution. `App` subclasses bind "app"; `Resource`/`Service` base classes bind "framework".
3. App identity (`app_key`, `instance_name`, `instance_index`) is bound via `structlog.contextvars.bind_contextvars()` at two points: lifecycle hooks (sequential, safe) and execution dispatch (concurrent, protected by bind/clear cycle). `clear_contextvars()` in `finally` blocks prevents leakage.
4. `CURRENT_EXECUTION_ID` (already exists in `context.py`) is reused — no separate correlation ID mechanism.
5. QueueHandler uses a custom QueueListener subclass with `dequeue(timeout=0.2)` for batch flush — no separate timer thread, no shutdown race.
6. LogPersistenceHandler uses late-wiring via `set_database(db_service, loop)` called from `RuntimeQueryService.on_initialize()`. Thread-to-loop crossing uses `call_soon_threadsafe`.
7. Shutdown ordering: `shutdown_logging()` called from `Hassette.before_shutdown()` — runs before any Resource shutdown.
8. `log_retention_days` (default 3) is constrained `<= db_retention_days` by a Pydantic validator. `retention_expired` flag on the by-execution endpoint disambiguates expired vs. empty logs.
9. Size failsafe uses a dedicated pre-pass for `log_records` (deleted first, highest volume) before the existing execution-record loop.
10. LogTable gains `mode: "live" | "historical"`, `fetcher`, and `useLocalState` props. Historical mode: custom fetcher, no WS merge, no URL params, no updateLogSubscription.

## Constraints & Anti-Patterns
- Do NOT use `from __future__ import annotations` (breaks Pydantic).
- Do NOT create a separate correlation ID mechanism — reuse `CURRENT_EXECUTION_ID`.
- Do NOT add `session_id` FK on the logs table — sessions are being removed.
- Do NOT read context vars in the QueueListener background thread — stamp records before enqueue via a `logging.Filter` on the QueueHandler.
- Do NOT call `DatabaseService.enqueue()` directly from the QueueListener thread — use `call_soon_threadsafe`.
- `register_app_logger()` and `_resolve_app_key()` are REMOVED — do not use or replicate prefix-matching logic.
- Line length: 120 characters. Ruff for linting/formatting, Pyright for type checking.

## Design Doc References
- `## Architecture > Layer 1` — structlog processor chain, ProcessorFormatter, ConsoleRenderer/JSONRenderer
- `## Architecture > Layer 2` — dual context var binding (lifecycle + dispatch), source_tier as logger-bound
- `## Architecture > Layer 3` — QueueHandler/QueueListener, dequeue-timeout, shutdown_logging()
- `## Architecture > Layer 4` — migration 009, LogPersistenceHandler, retention, repository methods, REST endpoints
- `## Architecture > Layer 5` — LogTable modal interface, logs page, app detail invocation logs
- `## Key Constraints` — stdlib wrapping, context var read timing, shutdown ordering
- `## Edge Cases` — no execution context, DB not yet ready, queue overflow, empty execution logs
