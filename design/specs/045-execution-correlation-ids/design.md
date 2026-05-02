# Design: Per-Execution Correlation IDs

**Date:** 2026-04-29
**Status:** archived
**Issue:** #571

## Problem

Handler invocations and job executions in the telemetry system can only be identified by composite keys (listener_id/job_id + execution_start_ts + session_id). This makes it impossible to:

- Uniquely identify a single execution for debugging or log correlation
- Trace a handler execution back to the specific event that triggered it
- Correlate hassette executions with their originating Home Assistant event chains
- Propagate execution identity across async boundaries (spawned tasks, error handlers)

When investigating why an automation didn't fire or why a handler errored, there is no way to follow the chain from effect back to cause without manually cross-referencing timestamps.

## Goals

- Every handler invocation and job execution receives a globally unique trace identifier
- Handler invocations capture the identity and origin of their triggering event
- Execution identity is available during execution via a context variable, enabling future causal chain tracking
- All new identifiers are visible in the monitoring UI
- Event identifiers across all event sources use a consistent format

## Non-Goals

- Parent-child execution tracking (e.g., handler A triggered job B) — deferred to a follow-up issue. The context variable infrastructure is designed to support this without schema changes.
- Backwards compatibility for existing telemetry data — the sole user does not need data preservation.
- Indexing new columns — these are debugging aids, not query predicates. Indexes can be added later if query patterns demand them.

## User Scenarios

### Developer: Automation Debugger
- **Goal:** Trace a handler invocation back to the event that triggered it
- **Context:** Investigating why a handler errored or didn't fire as expected

#### Investigating a failed handler

1. **Opens the handler detail view**
   - Sees: list of recent invocations with status, duration, trace ID, trigger context, and origin
   - Decides: which invocation to investigate (the failed one)
   - Then: expands the error row to see the traceback

2. **Reads the trigger context ID and origin**
   - Sees: the originating event's context ID and whether it came from HA (LOCAL/REMOTE) or hassette
   - Decides: whether the issue is in the event source or the handler logic
   - Then: uses the context ID to cross-reference with HA logs or other handler invocations triggered by the same event

3. **Copies the trace ID for log correlation**
   - Sees: the execution's unique trace ID
   - Decides: to search application logs for this trace ID
   - Then: finds all log entries from that specific execution

## Functional Requirements

1. Every handler invocation must receive a unique trace identifier at execution time
2. Every job execution must receive a unique trace identifier at execution time
3. Handler invocations must capture the triggering event's identifier when available
4. Handler invocations must capture the triggering event's origin (local, remote, or internal)
5. All event sources must produce identifiers in a consistent string format
6. The trace identifier must be available during execution for code running within the handler or job
7. The trace identifier must not persist beyond the execution's lifetime
8. All new identifiers must be stored in the telemetry database
9. All new identifiers must be displayed in the monitoring UI tables
10. Old execution records (pre-migration) must render gracefully in the UI with placeholder values

## Edge Cases

1. **Execution cancelled before identifier assignment** — CancelledError raised before the trace ID is generated. The record must still be enqueued with whatever state is available; the context variable must be cleaned up.
2. **Event without a triggering context** — Job executions have no triggering event. Trigger fields must be nullable and render as placeholders in the UI.
3. **Internal events with no external origin** — Hassette-generated events (service status, file watcher) must produce valid identifiers and a distinguishable origin.
4. **Concurrent executions** — Multiple handlers firing simultaneously must each get independent trace IDs and independent context variable scopes. asyncio task isolation guarantees this.

## Acceptance Criteria

1. A handler invocation row in the database has a non-empty trace identifier
2. A job execution row in the database has a non-empty trace identifier
3. A handler invocation triggered by a Home Assistant event shows the event's context ID and origin ("LOCAL" or "REMOTE")
4. A handler invocation triggered by an internal event shows the event's context ID and origin ("HASSETTE")
5. The trace identifier is readable during execution via a context variable
6. The context variable returns nothing after the execution completes
7. The context variable returns nothing after a cancelled execution
8. The monitoring UI shows trace ID, trigger context, and origin columns in the appropriate tables
9. Pre-existing rows render with placeholder values instead of crashing
10. All event sources produce string-format identifiers

## Dependencies and Assumptions

- aiosqlite supports `ALTER TABLE ADD COLUMN` for nullable columns (confirmed — SQLite 3.2+)
- asyncio copies context variables to spawned tasks automatically (Python 3.7+ guarantee)
- The OpenAPI schema generation pipeline (`scripts/export_schemas.py` → `openapi-typescript`) propagates new Pydantic fields to frontend types

## Architecture

### Event ID Unification

`HassettePayload.event_id` currently uses an incrementing `int` via `itertools.count(1)` that resets on restart. `HassPayload.event_id` returns a UUID string via `context.id`. These must be unified to `str` (UUID4) so `trigger_context_id` extraction works uniformly.

**Changes to `src/hassette/events/base.py`:**
- Remove `HASSETTE_EVENT_ID_SEQ = itertools.count(1)`
- Change `HassettePayload.event_id` from `int` field with counter default to `str` field with `uuid.uuid4()` default. Add docstring noting the UUID is payload-instance-scoped: each `HassettePayload(...)` construction generates a new ID. Unlike HA's `context.id` (stable across all handlers receiving the same event), reconstructed hassette payloads get different IDs. `trigger_context_id` for hassette events identifies a single handler's view of an event, not the event itself.
- Add `origin: str = "HASSETTE"` to `HassettePayload`

**Changes to `src/hassette/events/base.py` (EventPayload base):**
- Add `origin: str = "UNKNOWN"` to `EventPayload` so `_build_record()` can read `cmd.event.payload.origin` without Pyright errors. `HassPayload.origin` (currently `Literal["LOCAL", "REMOTE"]`) is a str subtype and remains compatible. `HassettePayload.origin` overrides with `"HASSETTE"`.
- Add `event_id: str` to `EventPayload` — `HassettePayload` overrides with a UUID4 default factory field; `HassPayload` overrides via its existing `context.id` property. Implementation note: the property/field interaction in frozen dataclasses with slots needs care — may require `HassPayload.event_id` to become a field set at construction from `context.id`, or `EventPayload.event_id` to be a property.

**Ripple:** `service_watcher.py:451` uses `%d` format specifier for `event.payload.event_id` — must change to `%s`.

### ContextVar Infrastructure

Add `CURRENT_EXECUTION_ID: ContextVar[str | None]` to `src/hassette/context.py` alongside existing context variables. Default is `None`.

Set in `CommandExecutor._execute()` before `track_execution()`, reset in a `finally` block wrapping the entire try/except (including the CancelledError re-raise path). Uses the token-based `set()`/`reset()` pattern already established in `context.py:use()`.

This ContextVar is the hook for future `parent_execution_id` — when that feature lands, `Scheduler.run_in()` reads `CURRENT_EXECUTION_ID.get()` to capture the spawning execution's ID and stores it on the `ScheduledJob`. No schema or executor changes will be needed.

### Data Model Changes

**`HandlerInvocationRecord`** (`src/hassette/bus/invocation_record.py`):
- `execution_id: str | None = None` — UUID4, populated by `_build_record()`. `None` (not empty string) for missing values, consistent with `session_id` and `error_type` conventions in the same file.
- `trigger_context_id: str | None = None` — from `cmd.event.payload.event_id`
- `trigger_origin: str | None = None` — from `cmd.event.payload.origin` (works for both `HassPayload` and `HassettePayload` after the origin field is added)

**`JobExecutionRecord`** (`src/hassette/scheduler/classes.py`):
- `execution_id: str | None = None` — UUID4, populated by `_build_record()`

**`HandlerInvocation`** (`src/hassette/core/telemetry_models.py`):
- `execution_id: str | None = None`
- `trigger_context_id: str | None = None`
- `trigger_origin: str | None = None`

**`JobExecution`** (`src/hassette/core/telemetry_models.py`):
- `execution_id: str | None = None`

### Execution Wiring

The ContextVar lifecycle lives in `_execute_handler()` and `_execute_job()`, not in `_execute()`. This ensures the ContextVar is set for the entire duration including spawned error handler tasks (which inherit context at `task_bucket.spawn()` time).

In `CommandExecutor._execute_handler()` / `_execute_job()`:
1. Generate `execution_id = str(uuid.uuid4())`
2. Set `token = CURRENT_EXECUTION_ID.set(execution_id)`
3. Wrap the entire method body (`await self._execute(...)` + error handler `task_bucket.spawn(...)`) in `try/finally` with `CURRENT_EXECUTION_ID.reset(token)`
4. Pass `execution_id` to `_execute()` as a new parameter

In `CommandExecutor._execute()`:
- Accept `execution_id: str` parameter, pass to `_build_record()`
- No ContextVar set/reset here — handled by caller

In `CommandExecutor._build_record()`:
- Accept `execution_id: str` parameter
- For `InvokeHandler`: extract `trigger_context_id = cmd.event.payload.event_id` and `trigger_origin = cmd.event.payload.origin` (both attributes exist on `EventPayload` base after the unification)
- For `ExecuteJob`: only `execution_id` (no trigger fields — jobs have no triggering event)

### Database Migration

New Alembic migration adding nullable TEXT columns:
- `handler_invocations`: `execution_id`, `trigger_context_id`, `trigger_origin`
- `job_executions`: `execution_id`

The `downgrade()` function raises `NotImplementedError("migration is not reversible — execution_id data would be lost")`. This is consistent with the non-goal of no backwards compatibility and prevents accidental rollback.

### Repository SQL Updates

Refactor `src/hassette/core/telemetry_repository.py` to eliminate column-string duplication between `persist_batch()` and `persist_batch_with_fk_fallback()`. Extract shared `_inv_insert_params(record: HandlerInvocationRecord) -> dict` and `_job_insert_params(record: JobExecutionRecord) -> dict` functions. Both INSERT paths derive their column lists and parameter dicts from these shared functions, making divergence structurally impossible. The four hardcoded string constants (`inv_cols`, `inv_vals`, `job_cols`, `job_vals`) in the FK fallback path are eliminated.

### Query Service Updates

`get_handler_invocations()` and `get_job_executions()` in `src/hassette/core/telemetry_query_service.py` need the new columns added to their SELECT lists.

### Frontend

After schema regeneration (`export_schemas.py` + `openapi-typescript`):
- Handler invocations table: add "Trace ID", "Trigger", and "Origin" columns
- Job executions table: add "Trace ID" column
- Update `COL_COUNT` constants for traceback row `colSpan`
- Null/empty values render as "—"
- Trace IDs and trigger context IDs use monospace styling per `design/context.md` conventions

## Alternatives Considered

### Incrementing integer IDs instead of UUID4

Simpler and more compact, but resets on restart (like the current `HassettePayload.event_id`), making cross-session correlation impossible. UUID4 is globally unique with no coordination needed.

### Storing trigger context as a JSON blob

Would capture the full HA context (id, parent_id, user_id) in one column. Rejected because: not indexable, harder to query, and `parent_id`/`user_id` are better modeled as separate columns if needed later.

### Keeping origin/event_id on subclasses only

Would avoid widening `EventPayload`. Rejected because `cmd.event.payload` is typed as `EventPayload[Any]` in `_build_record()`, and accessing `.origin` or `.event_id` on it would be a Pyright error without type narrowing. Adding to the base class makes the contract mechanical and avoids isinstance guards or helper functions in the executor.

## Test Strategy

**Unit tests:**
- ContextVar isolation: set during execution, `None` after, reset on `CancelledError`
- UUID generation: each execution produces a unique non-empty string
- `trigger_context_id` extraction from both `HassPayload` and `HassettePayload`
- `trigger_origin` extraction: "LOCAL"/"REMOTE" for HA events, "HASSETTE" for internal events
- `HassettePayload.event_id` produces UUID strings (not integers)

**Integration tests:**
- DB roundtrip: persist with all new fields via `persist_batch()`, query back via `get_handler_invocations()` / `get_job_executions()`, assert all three new fields are non-null. This catches divergence between INSERT columns, SELECT columns, and Pydantic model defaults.
- FK fallback roundtrip: trigger the FK violation path via a record with a non-existent FK, read back, assert new fields are populated. Catches divergence in the four hardcoded string constants.
- Null handling: records with `None` trigger fields persist and query without error

**Frontend:**
- Factory updates with new fields — must ship atomically with schema regeneration. Run `tsc --noEmit` immediately after `openapi-typescript` to catch compilation errors before committing.
- TypeScript compilation verifies type completeness
- Existing e2e tests exercise updated tables

## Documentation Updates

- `docs/pages/core-concepts/database-telemetry.md`: document `execution_id`, `trigger_context_id`, and `trigger_origin` columns with their semantics

## Impact

**Files modified:**
- `src/hassette/events/base.py` — HassettePayload.event_id type change, origin field, remove counter
- `src/hassette/core/service_watcher.py` — format string fix (`%d` → `%s`)
- `src/hassette/context.py` — new ContextVar
- `src/hassette/bus/invocation_record.py` — new fields on HandlerInvocationRecord
- `src/hassette/scheduler/classes.py` — new field on JobExecutionRecord
- `src/hassette/utils/execution.py` — no changes needed (ExecutionResult doesn't carry execution_id)
- `src/hassette/core/command_executor.py` — ID generation, ContextVar management, _build_record changes
- `src/hassette/core/telemetry_repository.py` — INSERT column updates (persist_batch + FK fallback)
- `src/hassette/core/telemetry_models.py` — Pydantic model field additions
- `src/hassette/core/telemetry_query_service.py` — SELECT column additions
- `src/hassette/migrations/versions/` — new migration file
- `frontend/src/components/app-detail/handler-invocations.tsx` — new columns
- `frontend/src/components/app-detail/job-executions.tsx` — new column
- `frontend/src/test/factories.ts` — factory updates
- `docs/pages/core-concepts/database-telemetry.md` — documentation

**Breaking API change:** `HassettePayload.event_id` changes from `int` to `str`. `HassettePayload` is in `hassette.events.__all__` — this is user-facing. Any user automation comparing `event.payload.event_id` against integers will silently fail. The implementation must include a `grep -r '\.event_id'` across the full codebase (including user app code) and the `HASSETTE_EVENT_ID_SEQ` counter must be explicitly removed. This should be noted as a breaking change in the commit message (`feat!:`).

**Blast radius:** Moderate. The event ID type change ripples through any code that consumes `HassettePayload.event_id` as an integer. The executor changes are in `_execute_handler()`, `_execute_job()`, and `_build_record()`. DB migration is additive (nullable columns only).

## Open Questions

None — all design decisions resolved during discovery.
