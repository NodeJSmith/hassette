# Prereq 3: Exception Handling Audit

**Status**: Decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately (pure analysis)

## Dependents

- [Prereq 1: Data model](./prereq-01-data-model.md) — status values depend on error classification decisions
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

## Decisions

### 1. Preserve the HassetteError vs Exception logging distinction

**Decision**: Yes.

`HassetteError` → `logger.error("...")` (one-line message, no traceback). General `Exception` → `logger.exception("...")` (message + traceback). The executor checks `isinstance(exc, HassetteError)` to choose the log method.

Framework errors (rate limit exceeded, invalid config, etc.) produce clean log lines. Unexpected errors get full tracebacks for debugging. Good UX worth preserving.

### 2. Executor owns timing directly, not via `track_execution()`

**Decision**: Executor owns timing directly.

`track_execution()` re-raises all exceptions, but the executor needs to swallow non-Cancelled exceptions. Fighting the context manager's semantics isn't worth it. The executor captures `time.monotonic()` at the start of invocation and computes `duration_ms` in the `finally` block. The wall-clock `Instant` is captured separately by the executor (see [prereq 1](./prereq-01-data-model.md) — "`ExecutionResult` stays monotonic-only" aside).

`track_execution()` remains available for user code and other contexts where re-raise-after-capture is the right behavior.

### 3. CancelledError produces a record, then re-raises

**Decision**: Yes, produce a record with `status="cancelled"`, then re-raise.

The record is queued via `put_nowait()` before the re-raise, so the write queue still gets it. Swallowing `CancelledError` would break asyncio's cancellation machinery. See [prereq 1](./prereq-01-data-model.md) for full `cancelled` status documentation.

### 4. Executor does NOT handle `listener.once` removal

**Decision**: Keep `listener.once` removal in `_dispatch()`, not the executor.

`listener.once` is bus routing logic, not an execution concern:

```python
async def _dispatch(self, topic, event, listener):
    await self._executor.execute(InvokeHandler(...))
    if listener.once:
        self.remove_listener(listener)
```

The executor is focused on execution + recording. The bus owns listener lifecycle. Similarly, the executor does not own job rescheduling — that stays in `SchedulerService`.

## Executor exception contract (summary)

```
CancelledError     → record status="cancelled" → RE-RAISE
DependencyError    → record status="error", error_type="DependencyError" → logger.error() → SWALLOW
HassetteError      → record status="error" → logger.error() (clean, no traceback) → SWALLOW
Exception          → record status="error" → logger.exception() (with traceback) → SWALLOW
```

**What the executor owns**: invocation, timing, record creation, error classification, logging, error hooks (future).

**What the executor does NOT own**: listener lifecycle (`once` removal), job rescheduling, topic routing, DI resolution.

## Deliverable

This file (decisions finalized). Feeds directly into the `CommandExecutor` implementation and the test cases needed to verify behavioral equivalence with the current `_dispatch()` and `run_job()` methods.
