# Prereq 3: Exception Handling Audit

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately (pure analysis)

## Dependents

- [Prereq 1: HandlerInvocationRecord](./prereq-01-handler-invocation-record.md) — status values depend on error classification decisions
- [Prereq 5: Schema design](./prereq-05-schema-design.md) — status column values and error fields informed by this audit

## Problem

The Command Executor will absorb exception handling from `BusService._dispatch()` and `SchedulerService.run_job()`. These two methods have subtly different exception semantics. Before migrating, we need to document the exact current contract, decide what the executor should preserve, and identify anything worth changing (small userbase = right time to fix).

## Current exception semantics

### `BusService._dispatch()` (`core/bus_service.py:203-230`)

```
CancelledError     → record_cancelled() → RE-RAISE
DependencyError    → record_di_failure() → logger.error() → SWALLOW
HassetteError      → record_error() → logger.error() → SWALLOW
Exception          → record_error() → logger.exception() → SWALLOW
```

Key details:
- `DependencyError` is caught **before** `HassetteError` (its parent) to classify DI failures separately
- `HassetteError` uses `logger.error()` (no traceback) — framework errors have clean messages
- General `Exception` uses `logger.exception()` (with traceback) — unexpected errors get full context
- All non-CancelledError exceptions are swallowed to protect the bus dispatch loop
- The `finally` block handles `listener.once` removal regardless of outcome
- Each `_dispatch()` runs in its own spawned task (`task_bucket.spawn`)

### `SchedulerService.run_job()` (`core/scheduler_service.py:188-232`)

```
CancelledError     → track_execution() captures status="cancelled" → RE-RAISE
Exception          → track_execution() captures error details → logger.exception() → SWALLOW
```

Key details:
- Uses `track_execution()` context manager which captures timing + error info into `ExecutionResult`
- `track_execution()` re-raises ALL exceptions (including non-Cancelled) — the outer `except Exception` catches and swallows them
- No `DependencyError` or `HassetteError` distinction — jobs don't use the DI injection system
- The `finally` block always builds and appends a `JobExecutionRecord`

### `track_execution()` (`utils/execution.py:39-66`)

```
CancelledError     → status="cancelled" → RE-RAISE
Exception          → status="error", captures details → RE-RAISE
Success            → status="success"
```

**Critical**: `track_execution()` re-raises everything. It's a capture mechanism, not a swallow mechanism. The caller decides whether to swallow.

## Asymmetries to resolve

| Concern                       | Bus (`_dispatch`)                | Scheduler (`run_job`)            | Executor decision needed                        |
| ----------------------------- | -------------------------------- | -------------------------------- | ----------------------------------------------- |
| **DI failure classification** | Distinct `di_failure` status     | N/A (no DI)                      | Keep as error_type distinction, not status?     |
| **HassetteError logging**     | `logger.error()` (clean)         | Not distinguished                | Preserve the clean vs traceback distinction?    |
| **General Exception logging** | `logger.exception()` (traceback) | `logger.exception()` (traceback) | Same — no change needed                         |
| **Swallow behavior**          | Swallows non-Cancelled           | Swallows non-Cancelled           | Same — executor must swallow to protect callers |
| **Timing source**             | Inline `time.monotonic()`        | Delegated to `track_execution()` | Executor owns timing directly                   |
| **Record creation**           | N/A (only aggregates)            | In `finally` block               | Executor creates record in `finally`            |

## Questions to answer

### 1. Should the executor preserve the HassetteError vs Exception logging distinction?

**Current behavior**: `HassetteError` → `logger.error("...")` (one-line message). General `Exception` → `logger.exception("...")` (message + traceback).

**Recommendation**: Yes, preserve this. It's a good UX — framework errors (rate limit exceeded, invalid config, etc.) produce clean log lines. Unexpected errors get full tracebacks for debugging. The executor can check `isinstance(exc, HassetteError)` to choose the log level.

### 2. Should the executor use `track_execution()` or own timing directly?

**Current state**: `run_job()` delegates to `track_execution()`, `_dispatch()` does inline timing.

**Recommendation**: Executor owns timing directly. `track_execution()` re-raises all exceptions, but the executor needs to swallow non-Cancelled exceptions. Fighting the context manager's semantics isn't worth it. The executor's `_execute_handler()` and `_execute_job()` methods each have a `started = time.monotonic()` and compute duration in the `finally` block.

`track_execution()` remains available for user code and other contexts where re-raise-after-capture is the right behavior.

### 3. Should CancelledError produce a record?

**Current behavior**: `_dispatch()` records cancelled in metrics. `run_job()` records cancelled via `track_execution()`.

**Recommendation**: Yes, produce a record with `status="cancelled"`. Then re-raise. The record is queued via `put_nowait()` before the `raise`, so the write queue still gets it.

### 4. Should the executor handle `listener.once` removal?

**Current behavior**: `_dispatch()` removes one-shot listeners in its `finally` block.

**Recommendation**: No. `listener.once` is bus routing logic, not an execution concern. Keep it in `_dispatch()`:

```python
async def _dispatch(self, topic, event, listener):
    await self._executor.execute(InvokeHandler(...))
    if listener.once:
        self.remove_listener(listener)
```

This keeps the executor focused on execution + recording, and the bus focused on listener lifecycle.

## Deliverable

A decision doc (this file, updated with final decisions) that defines the executor's exception contract:

- What it catches, what it swallows, what it re-raises
- How it logs different exception types
- What status values it produces
- What it does NOT own (listener lifecycle, job rescheduling)

This directly feeds into the `CommandExecutor` implementation and the test cases needed to verify behavioral equivalence.
