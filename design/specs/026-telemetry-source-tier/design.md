# Design: Telemetry Source Tier Unification

**Date:** 2026-04-07
**Status:** approved
**Spec:** design/specs/2033-telemetry-source-tier/spec.md
**Research:** design/research/2026-04-07-telemetry-tier-separation/research.md

## Problem

The telemetry system uses a binary split (`db_id is None`) to determine whether executions produce database records. This makes framework errors invisible to the dashboard, hides orphaned records behind INNER JOINs, and conflates "internal actor" with "pending registration." See the spec's Problem Statement for the full breakdown.

## Non-Goals

Per spec: no OTel export, no causal linking, no retention policy changes, no backward-compatible migration, no performance benchmarking.

## Architecture

### Shared Type: `SourceTier`

Define `SourceTier = Literal['app', 'framework']` in `hassette/types/types.py`. Use this alias on every dataclass, model, and function signature that carries `source_tier`. The DB CHECK constraint is belt-and-suspenders; the `Literal` type is the primary defense. Pyright catches invalid values at type-check time; adding a third tier later requires updating the `Literal` union in one place.

### Schema Migration (destructive — drop and recreate)

Replace all existing migrations with a single fresh schema. Key changes from the current schema:

**New column on all tables**: `source_tier TEXT NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework'))` on `listeners`, `scheduled_jobs`, `handler_invocations`, `job_executions`, and `sessions` (default `'framework'` for sessions).

**Nullable FKs**: `listener_id INTEGER REFERENCES listeners(id) ON DELETE SET NULL` (nullable, not NOT NULL) on `handler_invocations`. Same for `job_id` on `job_executions`. This is already the post-migration-003 state; the fresh schema codifies it.

**New flag column**: `is_di_failure INTEGER NOT NULL DEFAULT 0` on `handler_invocations` and `job_executions`. Set at write time in `CommandExecutor._build_record()`. The exception object is available in `track_execution()`'s context — pass `isinstance(exc, DependencyError)` result through `ExecutionResult` as a new `is_di_failure: bool` field, then read it in `_build_record()`. This avoids the `error_type` string comparison entirely.

**CHECK constraints**: `CHECK (status IN ('success', 'error', 'cancelled'))` on `handler_invocations`, `job_executions`. `CHECK (duration_ms >= 0.0)` on the same tables. `CHECK (status IN ('running', 'stopped', 'crashed'))` on `sessions`.

**Updated views**:
```sql
CREATE VIEW active_app_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'app';
CREATE VIEW active_app_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'app';
CREATE VIEW active_framework_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'framework';
CREATE VIEW active_framework_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'framework';
-- Backward-compatible aliases for code that doesn't need tier filtering:
CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL;
CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL;
```

**Unique index**: The existing partial unique index on listeners includes `app_key` and `COALESCE(name, ...)`. Framework actors must provide a unique `name` with a component prefix (e.g., `"hassette.service_watcher.restart_service"`) to prevent natural key collisions when multiple framework components register handlers on the same topic.

### Data Flow: source_tier Propagation

The `source_tier` value flows from registration through execution to persistence. All types use `SourceTier` (the `Literal` alias), not bare `str`.

1. **Registration**: `Listener.create()` gains a `source_tier: SourceTier = 'app'` parameter. `ListenerRegistration` and `ScheduledJobRegistration` gain a `source_tier: SourceTier` field. `BusService._register_then_add_route()` reads `listener.source_tier` when building `ListenerRegistration`. Framework actors set `source_tier = 'framework'`; app actors set `source_tier = 'app'`.

2. **Dispatch**: `InvokeHandler` and `ExecuteJob` command dataclasses gain a `source_tier: SourceTier` field. Set at the dispatch site:
   - `bus_service.py:_make_tracked_invoke_fn()` reads `listener.source_tier` and passes it to `InvokeHandler`.
   - `scheduler_service.py:run_job()` reads `job.source_tier` (from `ScheduledJob`) and passes it to `ExecuteJob`.

3. **Record building**: `CommandExecutor._build_record()` reads `cmd.source_tier` and sets it on `HandlerInvocationRecord` / `JobExecutionRecord`.

4. **Persistence**: `TelemetryRepository.persist_batch()` includes `source_tier` in the INSERT column lists for both tables.

### Framework Actor Registration

Framework actors are currently registered at three sites — all bypass the telemetry pipeline:

- `core.py:318` — `SessionManager.on_service_crashed` handler
- `service_watcher.py:211-216` — 4 internal lifecycle listeners
- `app_handler.py:76-80` — file watcher change event handler

**Change**: Each site must register through the same `CommandExecutor.register_listener()` / `register_job()` path as user-app actors, with `app_key = '__hassette__'`, `source_tier = 'framework'`, and a unique `name` prefixed with `"hassette.<component>."`.

**Implementation**: Add a `register_framework_listener()` convenience method on `BusService` that calls `Listener.create(..., source_tier='framework', app_key='__hassette__')` and routes through `_register_then_add_route()`. Framework actors call this instead of the bare `bus.on_*()` methods.

**Pending registration tasks**: Framework listener registrations go into `_pending_registration_tasks['__hassette__']`. These are never drained by `await_registrations_complete()` (which is called per-app during reconciliation). This is intentional — framework registrations complete independently via the normal `mark_registered()` callback. The tasks are pruned by the existing `_pending_registration_tasks` list-pruning logic on the next `add_job()` call for `__hassette__`.

**Timing**: Framework actors register during `on_initialize()` of their owning Resource. The session row is created in Phase 1 (`core.py:295`) before any service starts (Phase 2), so `session_id` is always available when framework actors first execute. Framework registration tasks run during Phase 2 alongside service startup.

### Sentinel Guard and Null-FK Handling

**Current state** (`command_executor.py:373-388`): Records with `listener_id == 0` or `session_id == 0` are dropped as REGRESSION.

**New contract**:
- `listener_id == 0` / `job_id == 0` → REGRESSION sentinel (drop + log ERROR). This should never happen.
- `listener_id is None` / `job_id is None` → Pre-registration orphan or reconciliation orphan (persist normally, no error log).
- `session_id == 0` → REGRESSION sentinel (drop + log ERROR). Session is always available before any handler fires.

`HandlerInvocationRecord.listener_id` becomes `int | None`. `JobExecutionRecord.job_id` becomes `int | None`. The sentinel filter in `_persist_batch` checks `== 0` (drop) separately from `is None` (allow).

**No backfill**: If a handler fires before registration completes, the record persists with `listener_id = None`. No queue scanning or backfill UPDATE. Subsequent executions after registration completes will have the correct FK. This is the simplest path and consistent with reconciliation orphan handling. *(Note: the spec's FR-5b originally mentioned backfill as a preferred path — the spec must be updated to reflect this design decision. The "no backfill" rationale: queue-scanning complexity, mutex coordination with the drain loop, and a new race condition for a window measured in milliseconds.)*

**`_safe_session_id()` removal**: The current `_safe_session_id()` method returns `0` on `RuntimeError`. This is the old behavior being replaced. In the new pipeline, records enqueued before the session is available carry `session_id = None`. `CommandExecutor` must not drain the write queue until a session ID is available (the session row is the first DB write in Phase 1, and `CommandExecutor.serve()` starts in Phase 2 — this ordering is already guaranteed). The `session_id` is injected into records at drain time, not at enqueue time. Remove `_safe_session_id()` and replace with direct `self.hassette.session_id` access in `_build_record()`.

### Dispatch Path Changes

**Current**: `bus_service.py:307` checks `listener.db_id is None` to decide between `_make_internal_invoke_fn` (no telemetry) and `_make_tracked_invoke_fn` (telemetry). `scheduler_service.py:304` does the same for jobs.

**New**: Remove the `db_id is None` branch entirely. All listeners go through `_make_tracked_invoke_fn`. All jobs go through `CommandExecutor.execute(ExecuteJob(...))`. The `_make_internal_invoke_fn` method is deleted. The inner `db_id is None` guard inside `_make_tracked_invoke_fn` (lines 352-358) is also removed — when `db_id is None`, the `InvokeHandler` is created with `listener_id=None` and proceeds through the normal execution path.

For listeners where `db_id is None` at fire time (registration not yet complete), `_make_tracked_invoke_fn` creates an `InvokeHandler` with `listener_id=None` (read from `listener.db_id` which may still be None). The `source_tier` is read from `listener.source_tier` (set at creation time, always available).

### Reconciliation Safety

**Current**: `AppLifecycleService._reconcile_app_registrations()` iterates app instances and calls `CommandExecutor.reconcile_registrations(app_key, live_ids, ...)`.

**Change**: `__hassette__` is never in `AppHandler`'s instance registry because framework actors are not `App` instances — they're registered by `Hassette`, `ServiceWatcher`, and `AppHandler` directly. Therefore, `reconcile_registrations('__hassette__', ...)` is never called by the existing loop.

**Belt and suspenders**: Add an explicit guard in `reconcile_registrations()`: if `app_key == '__hassette__'`, log a WARNING and return immediately. This prevents silent retirement if a future code path accidentally routes the sentinel through reconciliation.

**User-app guard**: Add a Pydantic field validator on `AppConfig.app_key` that rejects `'__hassette__'` with a clear error message. This prevents users from accidentally using the sentinel.

### Query Changes

**`get_recent_errors()`**: Replace the two-query fan-out with a single UNION ALL:

```sql
SELECT 'handler' AS kind, hi.listener_id, l.app_key, l.handler_method, l.topic,
       NULL AS job_id, NULL AS job_name,
       hi.execution_start_ts, hi.duration_ms, hi.error_type, hi.error_message,
       hi.source_tier
FROM handler_invocations hi
LEFT JOIN listeners l ON l.id = hi.listener_id
WHERE hi.status = 'error' AND hi.execution_start_ts > ?
  AND hi.source_tier = ?
UNION ALL
SELECT 'job' AS kind, NULL, sj.app_key, sj.handler_method, NULL,
       je.job_id, sj.job_name,
       je.execution_start_ts, je.duration_ms, je.error_type, je.error_message,
       je.source_tier
FROM job_executions je
LEFT JOIN scheduled_jobs sj ON sj.id = je.job_id
WHERE je.status = 'error' AND je.execution_start_ts > ?
  AND je.source_tier = ?
ORDER BY execution_start_ts DESC
LIMIT ?
```

When `source_tier` is `'all'`, omit the `AND hi.source_tier = ?` clause entirely (no filter). Single-value cases use `= ?` (not `IN (?)`).

Key changes: LEFT JOIN (not INNER JOIN), single LIMIT, `source_tier` filter, discriminator column.

**`get_slow_handlers()`**: Same LEFT JOIN fix. Add `source_tier` filter.

**`get_all_app_summaries()`**: Both registration count queries AND activity count queries filter to `source_tier = 'app'` by default. Registration counts use `active_app_listeners` / `active_app_scheduled_jobs` views. Activity count queries add `WHERE l.source_tier = 'app'` / `WHERE sj.source_tier = 'app'` joins. This ensures `'__hassette__'` never appears in the returned dict.

**`get_global_summary()`**: Filter both listener and job activity counts to `source_tier = 'app'` by default.

**All endpoints**: Add `source_tier: Literal['app', 'framework', 'all'] | None = Query(default=None)` parameter. FastAPI validates automatically and returns 422 for invalid values. When `None`, default to `'app'`. When `'all'`, omit the source_tier WHERE clause. Document valid values in OpenAPI descriptions.

**`source_tier` on all models**: Add `source_tier: SourceTier` to `ListenerSummary`, `ListenerWithSummary`, `JobSummary`, `HandlerInvocation`, `JobExecution`, `HandlerErrorRecord`, `JobErrorRecord`, `HandlerErrorEntry`, `JobErrorEntry`. Add `l.source_tier` / `sj.source_tier` / `hi.source_tier` / `je.source_tier` to all corresponding SQL SELECT statements.

**Nullable response model fields**: `HandlerErrorEntry.listener_id` → `int | None`, `HandlerErrorEntry.app_key` → `str | None`, `HandlerErrorEntry.handler_method` → `str | None`, `HandlerErrorEntry.topic` → `str | None`. Same for `JobErrorEntry.job_id`, `JobErrorEntry.app_key`, `JobErrorEntry.job_name`, `JobErrorEntry.handler_method`. `HandlerErrorRecord` and `JobErrorRecord` in `telemetry_models.py` also get nullable fields. SPA contract: null `listener_id` → render "deleted handler" label with no detail link.

### Write Pipeline Resilience

**Bounded queue**: `CommandExecutor.__init__` changes from `asyncio.Queue()` to `asyncio.Queue(maxsize=config.telemetry_write_queue_max)` (default: 1000, configurable). On `put_nowait()` raising `asyncio.QueueFull`, log ERROR and increment `self._dropped_overflow` counter. No backpressure. Add a WARN-level log when queue reaches 75% capacity (rate-limited to avoid log spam).

**Retry envelope**: New `RetryableBatch` dataclass:
```python
@dataclass
class RetryableBatch:
    invocations: list[HandlerInvocationRecord]
    job_executions: list[JobExecutionRecord]
    retry_count: int = 0
```

Queue type annotation updated to `asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord | RetryableBatch]`.

**`_drain_and_persist` update**: Add an explicit `RetryableBatch` branch — when dequeued, expand contents into the current batch's invocations/job_executions lists. Add an `assert_never` style guard for type exhaustiveness.

**`_flush_queue` update**: Same `RetryableBatch` handling. Wrap `_persist_batch` in try/except — on failure, log count of dropped records and increment `_dropped_exhausted`. Do not propagate the exception (shutdown must complete).

**Error classification in `_persist_batch`**:
- `sqlite3.OperationalError` → retryable (re-enqueue as `RetryableBatch` with `retry_count + 1`; drop if `retry_count >= 3`)
- `sqlite3.IntegrityError` → FK violation path (see below)
- `sqlite3.DataError` / `sqlite3.ProgrammingError` → non-retryable, drop immediately + log REGRESSION
- Other `Exception` → non-retryable, drop immediately + log ERROR

If `retry_count >= 3`, increment `self._dropped_exhausted` counter.

**FK violation handling** (FR-18): Since `PRAGMA foreign_keys = ON` (`database_service.py:250`), an INSERT referencing a deleted parent raises `sqlite3.IntegrityError`. On `IntegrityError`, roll back the transaction, then re-issue each record individually. For each row, catch `IntegrityError`, null only that row's FK, and retry the single INSERT. Log each nulled FK at WARNING. This handles the race where reconciliation deletes a parent between queue and flush without corrupting valid FK references in the same batch.

### Shutdown Ordering

`CommandExecutor` must shut down before `DatabaseService` to ensure `_flush_queue()` can still submit records. Enforce this via the Resource priority system: `CommandExecutor` gets a higher shutdown priority (shuts down first). Additionally, `_flush_queue` handles `RuntimeError` from `submit()` gracefully — if `DatabaseService` is already closed, log the count of unflushable records and increment `_dropped_exhausted` rather than raising.

### Endpoint Resilience

Add `try: ... except DB_ERRORS:` guards to these currently unguarded endpoints:
- `app_health` (`telemetry.py:110`)
- `app_listeners` (`telemetry.py:148`)
- `app_jobs` (`telemetry.py:162`)
- `handler_invocations` (`telemetry.py:173`)
- `job_executions` (`telemetry.py:185`)

Return empty lists or zero-value responses with 503 status, matching the existing pattern in `dashboard_kpis` and `dashboard_errors`.

### `/telemetry/status` Enhancement

Extend `TelemetryStatusResponse` with:
- `dropped_overflow: int = 0` — records dropped due to queue full
- `dropped_exhausted: int = 0` — records dropped after max retries

**DI path**: Add a `get_drop_counters() -> tuple[int, int]` method on `Hassette` that delegates to `CommandExecutor._dropped_overflow` and `_dropped_exhausted`. The `/telemetry/status` route injects `HassetteDep` (already available) and calls this method. Degraded-path values: `dropped_overflow=0, dropped_exhausted=0` when `CommandExecutor` is not yet initialized.

**SPA coupling**: The Preact SPA's TypeScript interface for `TelemetryStatusResponse` must be updated in the same PR as the model change — not as a follow-up.

### `__hassette__` API Surface

`GET /telemetry/app/__hassette__/health`, `GET /telemetry/app/__hassette__/listeners`, etc. are valid requests after this change. These endpoints are explicitly supported — they return framework actor health and registration data. Document `'__hassette__'` as a reserved `app_key` in OpenAPI description strings on the `app_key` path parameter: "Use `__hassette__` to query framework-internal actor telemetry."

### Dashboard UI (Preact SPA)

**Default behavior**: All dashboard endpoints default to `source_tier = 'app'`. The frontend doesn't need changes for the default user-app view to work correctly.

**Framework affordance**: Add a framework health indicator to the dashboard. The exact UX is flexible, but the minimum contract (AC-18): a visible element on the default dashboard that shows framework error count and provides one-click access to framework telemetry. Options for the implementer:
- A collapsible "System Health" section below the app grid
- A badge/counter in the status bar linking to framework-filtered view
- A toggle filter on the error feed

The indicator calls `/telemetry/dashboard/errors?source_tier=framework` (or `all`) and `/telemetry/dashboard/kpis?source_tier=framework` to populate.

### Migration Resilience

Since the migration is destructive (drop and recreate), add a startup check in `DatabaseService.on_initialize()`: if the database file exists but the schema version doesn't match the expected head revision, delete the file and recreate. Log at WARNING: "Database schema version mismatch — recreating database (no production data to preserve)." For the "version ahead of head" case (newer DB on older binary), always refuse auto-delete — log an ERROR with the version mismatch details and halt startup. Catch `FileNotFoundError` / `PermissionError` during file deletion and emit a human-readable error. This satisfies FR-20 for the current "no production users" assumption and must be revisited before public release.

### DI-Failure Flag

Replace the `LIKE 'Dependency%'` pattern in `telemetry_query_service.py` (3 occurrences in `get_listener_summary`, `get_global_summary`) with `SUM(CASE WHEN hi.is_di_failure = 1 THEN 1 ELSE 0 END)`. The flag is set via `ExecutionResult.is_di_failure` (new field) populated in `track_execution()` using `isinstance(exc, DependencyError)`. `_build_record()` reads `result.is_di_failure` — no string comparison involved.

### `once=True` Deferred Cleanup

Add a startup step in `SessionManager` (after session creation, when `session_id` is available): delete `once=True` listener rows from sessions where `stopped_at IS NOT NULL` and no invocations exist in the current session. Filter `WHERE source_tier = 'app'` to avoid accidentally deleting framework `once=True` listeners. This runs once per startup, cleaning up rows deferred from previous restarts.

## Alternatives Considered

### Separate tables for framework telemetry (Pattern 2 from prior art)
Home Assistant uses separate stores (Logbook vs System Log). Rejected because: doubles schema maintenance, prevents cross-tier correlation queries, and adds a second query path the dashboard must support. The unified-table approach (Pattern 1, Temporal's model) is simpler and more extensible.

### Nullable `app_key` + `owner_type` discriminator
Cleaner long-term model, but requires column-type change on every query that assumes `app_key` is non-null. The sentinel approach (`'__hassette__'`) works with existing indexes and GROUP BY queries unchanged. Can migrate to the discriminator model later if the sentinel becomes limiting.

### Backfill pre-registration records
Scan the write queue when registration completes and update null-FK records with the real FK. Rejected: adds queue-scanning complexity, mutex coordination with the drain loop, and a new race condition. The pre-registration window is milliseconds; orphan records are already handled by LEFT JOIN. *(Spec FR-5b to be updated to remove backfill language.)*

### Backpressure overflow policy
Block event delivery when the write queue is full. Rejected: telemetry is best-effort; blocking event delivery to preserve telemetry records inverts the priority. A slow DB should degrade telemetry, not automation execution.

## Test Strategy

### Unit tests
- `SourceTier` type: verify Pyright catches invalid `source_tier` values at type-check time.
- `source_tier` propagation: verify `InvokeHandler.source_tier` is set at dispatch, flows through `_build_record()`, and appears in the INSERT.
- Sentinel guard: verify `listener_id = 0` → dropped with REGRESSION log; `listener_id = None` → persisted without error.
- `RetryableBatch` envelope: verify re-enqueue on `OperationalError`, drop on max retries, drain on shutdown. Verify `_drain_and_persist` handles `RetryableBatch` items correctly.
- FK violation: verify row-by-row fallback on `IntegrityError`, only the violating row gets null FK.
- Queue overflow: verify `QueueFull` → dropped + counter incremented. Verify 75% capacity warning.
- `AppConfig` validator: verify `app_key = '__hassette__'` → `ValueError`.
- DI-failure flag: verify `is_di_failure = True` when `DependencyError` is raised (via `ExecutionResult.is_di_failure`).
- CHECK constraints: verify rejected values at the schema level.
- Error classification: verify `OperationalError` → retry, `IntegrityError` → FK path, `DataError` → drop + REGRESSION log.

### Integration tests
- Framework actor end-to-end: register a framework listener via `HassetteHarness`, trigger an error, query the dashboard errors endpoint with `?source_tier=framework`, verify the record appears.
- Pre-registration orphan: gate registration with `asyncio.Event`, fire handler before gate opens, verify record persists with `listener_id = None`.
- Reconciliation safety: register framework + app actors, run full reconciliation, verify framework actors survive. Verify reconciliation guard rejects `'__hassette__'`.
- `get_recent_errors` UNION ALL: insert mixed handler/job errors, verify correct ordering and limit behavior.
- LEFT JOIN orphan visibility: delete a listener registration, verify its invocations still appear in queries with "deleted handler" label.
- FK violation retry: simulate reconciliation deleting a parent while records are queued, verify records persist as orphans.
- `get_all_app_summaries` tier isolation: register framework actors, verify `'__hassette__'` not in returned dict.
- Shutdown ordering: force `DatabaseService` shutdown before `CommandExecutor`, verify graceful degradation (logged drops, no crash).

### E2E tests (Playwright)
- Dashboard default view shows app-tier errors only.
- Framework affordance is visible on default dashboard.
- Clicking affordance reveals framework errors with source tier tag.
- Dropped-records counter appears in `/telemetry/status` after simulated overflow.

## Open Questions

*OQ-1 (app_key semantics) — resolved: sentinel `'__hassette__'` selected.*

1. **Dashboard UX for framework telemetry.** The design provides the API contract (`?source_tier=` parameter) and minimum UX constraint (visible affordance). The exact component/layout is left to the implementer — collapsible section, badge, or filter toggle are all valid. This should be decided during WP implementation for the dashboard, not upfront.

2. **Dispatch concurrency limits.** The spec identified unbounded dispatch tasks as an OOM vector. This design does not add a semaphore — the bounded write queue (configurable, default 1000) provides an indirect bound on memory growth from telemetry records, but dispatch task count is still unbounded. If this becomes a problem, add a `config.bus_max_concurrent_dispatches` semaphore in a follow-up.

3. **Reconciliation scalability.** The `NOT IN (?, ?, ...)` pattern in `reconcile_registrations` degrades at high listener counts. This design does not change the reconciliation SQL. If monitoring (via query timing logs) shows degradation, switch to a temp-table or CTE approach in a follow-up.

## Impact

### Files modified

**Schema**: New single migration replacing 001-006. All tables gain `source_tier`, CHECK constraints. `handler_invocations.listener_id` and `job_executions.job_id` become nullable. New `is_di_failure` column. Updated views.

**Types**: `types/types.py` — `SourceTier = Literal['app', 'framework']`

**Core**:
- `command_executor.py` — nullable FK types, sentinel guard update, `RetryableBatch`, bounded queue (configurable), retry logic with error classification, FK violation row-by-row fallback, `dropped_*` counters, 75% capacity warning, `source_tier` on `_build_record()`, `_safe_session_id()` removal, shutdown ordering priority, `_flush_queue` error handling
- `commands.py` — `source_tier: SourceTier` on `InvokeHandler` and `ExecuteJob`
- `bus_service.py` — remove `_make_internal_invoke_fn`, remove inner `db_id is None` guard in `_make_tracked_invoke_fn`, all listeners through tracked path, `source_tier` on dispatch, `register_framework_listener()` convenience method
- `bus/listeners.py` — `source_tier: SourceTier` on `Listener`, `Listener.create()` gains `source_tier` parameter
- `bus/invocation_record.py` — `listener_id: int | None`, `source_tier: SourceTier` on `HandlerInvocationRecord`
- `scheduler_service.py` — remove `db_id is None` branch, all jobs through `ExecuteJob`, `source_tier` on dispatch
- `scheduler/classes.py` — `source_tier: SourceTier` on `ScheduledJob`, `JobExecutionRecord.job_id: int | None`, `source_tier: SourceTier` on `JobExecutionRecord`
- `telemetry_repository.py` — `source_tier` in INSERT statements, reconciliation guard for `'__hassette__'`
- `telemetry_query_service.py` — LEFT JOINs, UNION ALL for errors, `source_tier` filter parameter on all query methods, `is_di_failure` flag queries, `active_app_*` views, `source_tier` in all SELECTs
- `telemetry_models.py` — nullable fields on error/slow records, `source_tier: SourceTier` on all summary/detail models (`ListenerSummary`, `JobSummary`, `HandlerInvocation`, `JobExecution`, `HandlerErrorRecord`, `JobErrorRecord`, `SlowHandlerRecord`, `SessionRecord`)
- `registration.py` — `source_tier: SourceTier` on `ListenerRegistration` and `ScheduledJobRegistration`
- `database_service.py` — schema version check for auto-recreate (FR-20), version-ahead guard
- `session_manager.py` — `once=True` deferred cleanup at startup (after session creation, filtered to `source_tier = 'app'`)
- `core.py` — framework actor registration via `register_framework_listener()`, `get_drop_counters()` getter
- `service_watcher.py` — framework actor registration with component-prefixed names
- `app_handler.py` — framework actor registration, `AppConfig` validator for `'__hassette__'`
- `utils/execution.py` — `ExecutionResult.is_di_failure: bool` field

**Web**:
- `web/routes/telemetry.py` — `source_tier: Literal['app', 'framework', 'all'] | None` query parameter on all endpoints, DB_ERRORS guards on 5 unguarded endpoints, `dropped_*` in status response via `HassetteDep`
- `web/models.py` — nullable fields on error/slow response models, `source_tier: SourceTier` on all response models, `dropped_overflow: int = 0` / `dropped_exhausted: int = 0` on `TelemetryStatusResponse`
- `web/telemetry_helpers.py` — remove `LIKE 'Dependency%'` usage if any remains

**Config**: `config.py` — `telemetry_write_queue_max: int = 1000`

**Frontend**: Dashboard Preact components — framework health affordance (badge/section/toggle). TypeScript interface updates for `TelemetryStatusResponse` and nullable model fields (same PR as backend changes).

**Tests**: New integration test module for framework actor telemetry. Extended `HassetteHarness` for `'__hassette__'` registration. New E2E tests for dashboard framework affordance. Shutdown ordering test. Tier isolation test for `get_all_app_summaries`.

### Blast radius

High — touches the full telemetry pipeline from dispatch through persistence to dashboard. The Implementation Sequencing section in the spec defines Tier 1 (correctness fixes) as independently mergeable, reducing risk per PR.
