# Prereq 1: Design the Full Data Model

**Status**: Design decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — data model defines all table structures
- [Prereq 3: Exception handling audit](./prereq-03-exception-handling-audit.md) — status enum values depend on how errors are classified

## Supersedes

- [Prereq 2: Stable listener identity](./prereq-02-stable-listener-identity.md) — parent tables with natural keys eliminate the need for a `stable_key` composite string

## Problem

Bus handlers have no per-invocation records. `ListenerMetrics` (`bus/metrics.py:13`) tracks only aggregates (total counts, min/max timing, last error). There is no equivalent of `JobExecutionRecord` (`scheduler/classes.py:182`) for bus event handlers. The Command Executor needs a typed record to produce for every handler invocation.

Additionally, the existing `JobExecutionRecord` has design issues that should be fixed now while the userbase is small:
- `started_at: float` is a bare `time.time()` float with no semantic type safety
- `owner: str` is an opaque string (`"KitchenLights.KitchenLights.0"`) that must be reverse-engineered by `DataSyncService`
- `job_id: int` is process-local (resets on restart)

Both records should be designed together so they share conventions.

## Decisions Made

### Normalized schema: Parent tables + execution tables

Use a normalized design with parent tables for listeners and scheduled jobs, and slim execution tables that reference them via FK.

**Why**: Execution records are high-volume writes. Repeating `app_key`, `instance_index`, `handler_method`, `topic` on every row wastes space and write bandwidth. Parent tables store this once, execution records carry only a FK + execution-specific fields. Parent tables also provide a natural home for listener/job configuration metadata (debounce, throttle, trigger type, kwargs) that currently exists only in memory.

**Registration overhead**: One INSERT/upsert per listener/job at startup. For a typical setup (20-50 listeners, 10-20 jobs), this is negligible.

**Read overhead**: JOINs against tiny parent tables (dozens of rows, fully cached by SQLite) are effectively free.

**Cross-restart identity**: Parent tables use natural keys for upsert on restart. The auto-increment `id` stays as PK / FK target.

```sql
-- On restart, same logical listener gets updated, not duplicated
INSERT INTO listeners (app_key, instance_index, handler_method, topic, ...)
VALUES (?, ?, ?, ?, ...)
ON CONFLICT (app_key, instance_index, handler_method, topic)
DO UPDATE SET last_registered_at = ?, debounce = ?, ...
```

This eliminates the need for [prereq 2's `stable_key`](./prereq-02-stable-listener-identity.md) — the parent table's natural key provides cross-restart identity directly.

### Timestamps: Use `whenever.Instant`, store as REAL

The codebase already uses the `whenever` library extensively (`ZonedDateTime`, `Instant`, etc.) and has a `now()` helper in `date_utils.py`. Execution records should use `Instant` (a UTC moment in time with no timezone) rather than bare `float` from `time.time()`.

- **Python type**: `Instant` from `whenever`
- **DB storage**: REAL (UTC epoch seconds) — fast comparisons, no ambiguity
- **Display**: Convert to `ZonedDateTime` in the UI layer (browser `toLocaleString()` or server-side `instant.to_system_tz()`)
- **Field name**: `execution_start_ts` (not `started_at` — follows project naming convention)

No need to store `execution_end_ts` — `duration_ms` is sufficient and avoids redundant computation.

### Identity: Structured fields, not opaque `owner` string

Replace the opaque `owner: str` with structured fields sourced from the `App` class:

| Field            | Source                                                       | Example                   |
| ---------------- | ------------------------------------------------------------ | ------------------------- |
| `app_key`        | `App.app_manifest.app_key` (new convenience property on App) | `"kitchen.KitchenLights"` |
| `instance_index` | `App.index` (existing, line 83 of app.py)                    | `0`                       |

`app_key` comes from the manifest — it's either set in `hassette.toml` or auto-derived as `f"{module_path}.{ClassName}"` for auto-detected apps. User-controlled and deterministic.

`instance_index` is deterministic — assigned by `enumerate()` over the config list in `AppFactory.create_instances()` (line 61 of app_factory.py). Same config → same index.

The old `owner_id` string will **not** be stored on the new records. `DataSyncService` lookups will migrate to use `app_key` + `instance_index`.

### Handler identity: Just the method name

`callable_name()` returns fully-qualified names like `"my_apps.kitchen.KitchenLights.on_light_change"`. This is redundant when `app_key` already identifies the app and module.

Store only the method name: `"on_light_change"`. The existing `callable_short_name()` utility (`utils/func_utils.py:91`) with `num_parts=1` already extracts this.

### Status values: Unified `error`, no distinct `di_failure`

Status values shared across both record types:

- `"success"` — handler/job completed without raising
- `"error"` — handler/job raised an exception (details in `error_type`, `error_message`, `error_traceback`)
- `"cancelled"` — handler/job was interrupted by `asyncio.CancelledError`, typically during framework shutdown when `TaskBucket` cancels running tasks. Can also occur mid-session if a parent task is cancelled. Expected to be rare in practice. The `CancelledError` is always re-raised after recording — swallowing it would break asyncio's cancellation machinery.

DI failures are `status="error"` with `error_type="DependencyError"`. Queryable via `WHERE error_type = 'DependencyError'` without adding handler-specific status values.

### Trigger context: Topic only (for now)

Store `topic` on listener parent records. Richer trigger context (entity_id, event data) deferred to a follow-up.

### Source capture: AST-based registration source extraction

Store the source code of each registration call on the parent tables for debugging and UI display. This gives users immediate visibility into what a listener filters on (predicates, topics, conditions) and how a job is configured — without needing to open their editor.

**Approach**: Use `inspect.stack()` to get the caller's filename and line number, then `ast.parse()` the source file and walk the tree to find the `Call` node at that line. `ast.get_source_segment(source, node)` (Python 3.8+, we require 3.11+) extracts the exact source text.

**Two fields on each parent table:**

| Field                 | Type           | Description                                                        |
| --------------------- | -------------- | ------------------------------------------------------------------ |
| `source_location`     | `str`          | Always captured. `"apps/kitchen.py:42"`                            |
| `registration_source` | `str \| None`  | Best-effort source snippet. `None` if capture fails (e.g., REPL). |

**Performance**: `ast.parse()` is called once per source file at startup (cached per file path). With 20-50 registrations across 5-10 app files, this is negligible. Never runs on the hot path.

**Edge cases**:
- Dynamically generated registrations (e.g., in a loop) resolve to the same source node — still useful context.
- REPL / `exec()` / no source file available → `source_location` from stack frame, `registration_source = None`.
- Decorators that wrap registration calls may shift the line number — the AST walk finds the call at the reported line, so this is only an issue if the decorator synthesizes a new call entirely (rare).

**Upsert behavior**: Both fields are updated on restart via `DO UPDATE SET`. The parent table always reflects the current source. Historical source changes are tracked by git, not the database.

**Why AST over raw text parsing**: Counting parens through raw source text breaks on multi-line calls, nested calls, comments containing parens, and string literals with parens. The AST handles all of these correctly with no special cases.

### Job name uniqueness: Validate at registration time

Scheduled jobs must have unique `job_name` values within an instance. The natural key for the `scheduled_jobs` parent table is `(app_key, instance_index, job_name)`.

**Why validation at registration, not DB constraint**: If a user registers the same method twice with different kwargs but no explicit name (both defaulting to `func.__name__`), a DB unique constraint would surface a confusing database error. Validating in `Scheduler.add_job()` at registration time produces a clear, actionable error: *"A job named 'open_blinds' already exists for this app instance. Provide a distinct name."*

Example of the problem this solves:
```python
# Both default to job_name="open_blinds" — collision
self.scheduler.run_daily(self.open_blinds, "07:00", kwargs={"reason": "morning"})
self.scheduler.run_daily(self.open_blinds, "17:00", kwargs={"reason": "after_work"})

# Fixed: explicit names
self.scheduler.run_daily(self.open_blinds, "07:00", name="open_blinds_morning", kwargs={"reason": "morning"})
self.scheduler.run_daily(self.open_blinds, "17:00", name="open_blinds_evening", kwargs={"reason": "after_work"})
```

### Args/kwargs serialization for scheduled jobs

Scheduled job `args` and `kwargs` are registration-time configuration that distinguish otherwise-identical job registrations. They should be stored on the `scheduled_jobs` parent table as JSON.

**Serialization approach**: Use `json.dumps()` with `default=str` for common non-JSON types (paths, datetimes, enums) and `sort_keys=True` for determinism. Fall back to a placeholder for truly unserializable objects:

```python
def safe_json_serialize(value: Any) -> str:
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return '"<NON_SERIALIZABLE>"'
```

The placeholder ensures non-serializable kwargs don't cause errors or create a new parent record on every restart. It's explicit enough that anyone seeing it in the DB knows the original value couldn't be captured.

## Proposed data model

### Parent tables (populated at registration time)

#### `listeners`

```python
@dataclass(frozen=True)
class ListenerRegistration:
    """Registration record for a bus event listener."""

    # Natural key (unique together)
    app_key: str              # "kitchen.KitchenLights"
    instance_index: int       # 0
    handler_method: str       # "on_light_change"
    topic: str                # "state_changed.light.kitchen"

    # Configuration metadata
    debounce: float | None    # seconds, or None
    throttle: float | None    # seconds, or None
    once: bool
    priority: int
    predicate_description: str | None  # human-readable predicate repr (see future note below)

    # Source capture
    source_location: str               # "apps/kitchen.py:42"
    registration_source: str | None    # AST-extracted source snippet, or None

    # Lifecycle
    first_registered_at: Instant
    last_registered_at: Instant
```

#### `scheduled_jobs`

```python
@dataclass(frozen=True)
class ScheduledJobRegistration:
    """Registration record for a scheduled job."""

    # Natural key (unique together)
    app_key: str              # "kitchen.KitchenLights"
    instance_index: int       # 0
    job_name: str             # "open_blinds_morning" (unique per instance)

    # Handler
    handler_method: str       # "open_blinds"

    # Trigger configuration (denormalized — not worth a separate table)
    trigger_type: str | None  # "cron", "interval", or None (one-shot)
    trigger_value: str | None # cron: "0 7 * * * 0", interval: "300.0" (seconds)
    repeat: bool

    # Registration-time arguments
    args_json: str            # safe_json_serialize(args)
    kwargs_json: str          # safe_json_serialize(kwargs)

    # Source capture
    source_location: str               # "apps/kitchen.py:58"
    registration_source: str | None    # AST-extracted source snippet, or None

    # Lifecycle
    first_registered_at: Instant
    last_registered_at: Instant
```

### Execution tables (high-frequency writes, slim)

#### `handler_invocations`

```python
@dataclass(frozen=True)
class HandlerInvocationRecord:
    """Record of a single bus handler invocation."""

    listener_id: int          # FK to listeners table

    # Execution
    execution_start_ts: Instant
    duration_ms: float
    status: str               # "success", "error", "cancelled"

    # Error (nullable)
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
```

#### `job_executions`

```python
@dataclass(frozen=True)
class JobExecutionRecord:
    """Record of a single scheduled job execution."""

    job_id: int               # FK to scheduled_jobs table

    # Execution
    execution_start_ts: Instant
    duration_ms: float
    status: str               # "success", "error", "cancelled"

    # Error (nullable)
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
```

Changes from current `JobExecutionRecord`:
- `started_at: float` → `execution_start_ts: Instant`
- `owner: str` → removed (identity lives on parent `scheduled_jobs` table)
- `job_id: int` (process-local) → FK to `scheduled_jobs` parent table
- `job_name: str` → removed (lives on parent table)
- `handler_method: str` → removed (lives on parent table)
- Now `frozen=True` (immutable)

### Aside: `ExecutionResult` stays monotonic-only

`ExecutionResult.started_at` (`utils/execution.py:19`) is `time.monotonic()` — not a wall-clock timestamp. Rename to `_monotonic_start` or similar to prevent anyone from treating it as a real timestamp.

`ExecutionResult` should **not** gain an `Instant` field. It stays as a pure timing/duration mechanism (monotonic clock — immune to NTP adjustments and system clock changes). The `CommandExecutor` captures the wall-clock `Instant` separately, right before invoking the handler/job, and passes it through to the record. This keeps concerns cleanly separated: `ExecutionResult` measures duration, `CommandExecutor` records when it happened.

## Prerequisite work

Before implementing the records:

1. **Add `app_key` property to `App`** — delegates to `self.app_manifest.app_key`. Small, self-contained change.
2. **Add job name uniqueness validation to `Scheduler.add_job()`** — raise a clear error if a job with the same name already exists for the instance.
3. **Verify `callable_short_name()` handles edge cases** — lambdas, partials, non-method callables. Already tested, but worth confirming coverage for the "method name only" use case.

## Deliverable

- `ListenerRegistration` and `ScheduledJobRegistration` dataclasses (parent table records)
- `HandlerInvocationRecord` dataclass in `src/hassette/bus/`
- Modernized `JobExecutionRecord` dataclass (in-place update in `src/hassette/scheduler/classes.py`)
- `safe_json_serialize()` utility for args/kwargs
- `capture_registration_source()` utility — AST-based source extraction with per-file caching
- `App.app_key` convenience property
- `Scheduler.add_job()` uniqueness validation
- `ExecutionResult.started_at` renamed
- Update all sites that construct `JobExecutionRecord` (currently just `scheduler_service.py:221-232`)

## Future work (not in scope)

- **Listener predicate storage**: Currently `predicate_description` stores a human-readable `repr()` of the predicate, and `registration_source` provides the full registration call (which includes the predicate expression as written). Eventually we should store the full predicate definition in a structured, serializable form so the dashboard can query and filter on predicate components — not just display them. This may require a serialization protocol on predicates (similar to the `safe_json_serialize` approach for kwargs). Deferred because predicates can be arbitrary callables today, and designing a serialization scheme for them is a separate effort. In the meantime, `registration_source` provides good visibility.
- **Richer trigger context on invocations**: Store the triggering entity_id, event type, or event data on handler invocation records for queries like "show all invocations triggered by `light.kitchen`".
- **Trigger normalization**: If trigger configurations become complex enough to warrant their own table (e.g., cron schedules with exclusion windows), break them out. For now, `trigger_type` + `trigger_value` on the parent table is sufficient.
