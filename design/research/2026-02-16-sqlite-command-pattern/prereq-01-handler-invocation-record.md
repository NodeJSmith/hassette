# Prereq 1: Design `HandlerInvocationRecord` Dataclass

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — record fields define table columns
- [Prereq 3: Exception handling audit](./prereq-03-exception-handling-audit.md) — status enum values depend on how errors are classified

## Problem

Bus handlers have no per-invocation records. `ListenerMetrics` (`bus/metrics.py:13`) tracks only aggregates (total counts, min/max timing, last error). There is no equivalent of `JobExecutionRecord` (`scheduler/classes.py:182`) for bus event handlers. The Command Executor needs a typed record to produce for every handler invocation.

## Scope

Create a `HandlerInvocationRecord` dataclass in `bus/`, mirroring `JobExecutionRecord`'s shape.

### Fields to design

**Identity fields** (how to find records for a specific handler):
- `stable_key: str` — from [prereq 2](./prereq-02-stable-listener-identity.md), composite key that survives restarts
- `owner: str` — resource unique_name (e.g. `"Hassette.AppHandler.MyApp.Bus"`)
- `topic: str` — event topic that was dispatched
- `handler_name: str` — module-qualified handler name

**Execution fields**:
- `started_at: float` — wall-clock timestamp (`time.time()`)
- `duration_ms: float` — monotonic-clock duration
- `status: str` — execution outcome

**Error fields** (nullable, populated only on failure):
- `error_type: str | None` — exception class name
- `error_message: str | None` — `str(exc)`
- `error_traceback: str | None` — `traceback.format_exc()`

### Key design decision: status enum values

`JobExecutionRecord` uses: `"success"`, `"error"`, `"cancelled"`

For handler invocations, the question is whether `DependencyError` (DI failures) gets a distinct status:

| Option                       | Status values                                 | Pros                                                                                                      | Cons                                                                        |
| ---------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **A: Unified `error`**       | `success`, `error`, `cancelled`               | Simpler schema, matches `JobExecutionRecord`, DI failures distinguished by `error_type="DependencyError"` | Requires filtering by `error_type` to separate DI failures from real errors |
| **B: Distinct `di_failure`** | `success`, `error`, `di_failure`, `cancelled` | Explicit classification, fast queries for DI issues                                                       | Handler-specific status that doesn't apply to jobs, schema divergence       |

**Recommendation**: Option A (unified `error`). The `error_type` column provides the same queryability (`WHERE error_type = 'DependencyError'`) without adding handler-specific status values to a shared enum.

### Reference: `JobExecutionRecord` (the model to mirror)

```python
# scheduler/classes.py:182-194
@dataclass
class JobExecutionRecord:
    job_id: int
    job_name: str
    owner: str
    started_at: float
    duration_ms: float
    status: str  # "success", "error", "cancelled"
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
```

## Deliverable

A `HandlerInvocationRecord` dataclass in `src/hassette/bus/` with frozen=True, matching `JobExecutionRecord`'s conventions. No behavioral changes — just the data model.
