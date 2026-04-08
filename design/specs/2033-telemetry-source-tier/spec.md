---
feature_number: "2033"
feature_slug: "telemetry-source-tier"
status: "approved"
created: "2026-04-07"
---

# Spec: Telemetry Architecture Redesign — Source Tier Unification

## Problem Statement

Hassette's telemetry system was designed around a binary split: user-app executions are persisted to the database and surfaced on the dashboard, while internal framework operations (heartbeat, reconnection, file watching, session management) are logged to stdout only. This architecture creates three categories of problems:

1. **Framework blindness.** When internal framework operations fail — WebSocket reconnection loops, scheduler heartbeats timing out, file watcher crashes — no record reaches the dashboard. Operators monitoring the system see "all healthy" while the framework is actively failing. Users whose automations crash due to a framework issue see the automation error but have no visibility into the root cause.

2. **Data integrity gaps.** Execution records that lose their parent registration (via `ON DELETE SET NULL` during reconciliation) are preserved in the database but hidden from all dashboard queries due to INNER JOINs. Error records exist but are unreachable — the dashboard reports "no recent errors" when errors are present.

3. **Ambiguous dispatch logic.** The mechanism that distinguishes internal from tracked executions (`db_id is None`) conflates two meanings: "this is an internal framework actor that should never be tracked" and "this is a user-app actor whose database registration hasn't completed yet." A user-app handler that fires before registration completes silently falls into the untracked path with no telemetry record.

These problems were catalogued in a 20-finding adversarial review (challenge) and validated against industry patterns (prior art survey of Temporal, Airflow, Dagster, Home Assistant, n8n, OpenTelemetry).

## Goals

1. All execution records — user-app and framework-internal — are persisted to the same database tables and are queryable from the dashboard.
2. Framework and user-app records are distinguishable via a source tier annotation, following the metadata-tag-on-every-record pattern used by Temporal and OpenTelemetry.
3. The dashboard error feed can reflect all error types regardless of source tier when the appropriate filter is active; the default view shows user-app errors only.
4. Orphaned execution records (where the parent registration has been deleted) remain visible in dashboard queries with appropriate labeling.
5. Operators can identify slow, flaky, or failing framework operations using the same telemetry infrastructure available for user-app operations.
6. Users can trace from a user-app failure to its framework root cause when one exists.
7. The telemetry write pipeline is resilient to transient database failures — records are not silently dropped.
8. All telemetry query endpoints degrade gracefully on database unavailability.

## Non-Goals

1. OpenTelemetry export or OTel-compatible span format — the source tier concept is inspired by OTel's instrumentation scope but does not require OTel integration.
2. Causal linking between framework errors and user-app failures — correlation is based on temporal proximity and shared session, not explicit causal chains.
3. Retention policy changes — record cleanup and pruning are out of scope.
4. Backward-compatible migration — there are no production users; the database will be recreated from scratch.
5. Performance benchmarking of the new query patterns — correctness first; optimization is a follow-up if needed.

## Implementation Sequencing

This spec bundles correctness fixes with an architectural redesign. The requirements are ordered by dependency:

**Tier 1 — Independent correctness fixes (no dependency on source tier decisions):**
FR-7, FR-8, FR-9, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-18. These can be implemented and merged independently of the source tier architecture.

**Tier 2 — Source tier architecture (OQ-1 resolved: sentinel `app_key = "__hassette__"` — see FR-4, FR-6):**
FR-1, FR-2, FR-3, FR-4, FR-5, FR-5a, FR-5b, FR-6, FR-16, FR-17, FR-19, FR-21. These depend on the source tier column and framework actor registration.

Tier 1 changes are safe intermediate merge points. Tier 2 builds on top.

## User Scenarios

### Operator: Someone monitoring the system after deployment

- **Goal:** Understand the health of both user automations and the framework itself from a single dashboard.
- **Context:** Checking the dashboard after a deployment or after receiving an alert that something isn't working.

#### Investigating a silent failure

1. **Opens the dashboard**
   - Sees: Error feed showing recent user-app errors. A visible indicator (badge, count, or section header) signals N framework errors are available.
   - Decides: Whether to investigate user-app errors or check framework health.

2. **Activates the framework telemetry affordance (clicks badge/toggle/section)**
   - Sees: Framework error records appear, each tagged with source tier and framework operation name (e.g., "WebSocket reconnection failure").
   - Decides: Whether this framework error is related to user-app failures occurring around the same time.

3. **Checks a user-app that failed around the same time**
   - Sees: The app's error record alongside the framework error in the timeline.
   - Decides: That the framework disconnection caused the app failure.

#### Identifying flaky framework operations

1. **Views framework telemetry**
   - Sees: Execution history for framework operations — success rates, average durations, error frequency.
   - Decides: Which framework operations are slow or unreliable.

### App Developer: Someone writing Hassette automations

- **Goal:** Understand why their automation failed and whether it was their code or a system issue.
- **Context:** An automation stopped working and they're checking the dashboard to diagnose.

#### Diagnosing an automation failure

1. **Opens their app's detail page**
   - Sees: Handler and job execution history, including any errors.
   - Decides: Whether the error is in their handler code or caused by something external.

2. **Sees an error but the handler code looks correct**
   - Sees: Framework errors that occurred during the same time window, tagged distinctly from app errors.
   - Decides: That the framework was the root cause, not their automation code.

#### Handler fired but shows no telemetry

1. **Writes a debounced handler, confirms it fires (logs show output)**
   - Sees: Dashboard shows zero invocations for the handler.
   - Decides: Something is wrong with the telemetry system, not their code.

2. **Under the new spec: checks the dashboard after the handler fires**
   - Sees: An invocation record confirming the handler ran, even if it fired before DB registration completed (shown as an orphan record with null FK).
   - Decides: The system is working correctly; proceeds with confidence.

## Functional Requirements

### Source Tier Annotation

FR-1: Every execution record (handler invocation, job execution) must carry a `source_tier` annotation that distinguishes user-app records from framework-internal records. The sessions table must carry `source_tier TEXT NOT NULL DEFAULT 'framework'` (sessions are always created by the framework). The `source_tier` column must be constrained at the database level via `CHECK (source_tier IN ('app', 'framework'))` on all tables that carry it. Two tiers are sufficient for the foreseeable future; adding a third tier requires a schema migration.

FR-2: The source tier annotation must be set at record creation time and must be immutable after creation.

FR-3: Registration records (listeners, scheduled jobs) must carry the same source tier annotation as their associated execution records. `ListenerSummary` and `JobSummary` models must include a `source_tier` field populated from the registration row. The `active_listeners` and `active_scheduled_jobs` views must be updated with `source_tier`-aware variants. All dashboard summary queries that report registration counts must filter to the appropriate source tier and must not count framework actor registrations in user-app summaries. Activity count queries (`get_global_summary`, `get_all_app_summaries`) must also filter by `source_tier = 'app'` by default; a separate query parameter or API method must expose framework-tier activity counts when explicitly requested.

### Framework Actor Registration

FR-4: Internal framework operations (event handlers and scheduled jobs registered by the framework itself, not by user apps) must be registered in the database and produce execution records through the same pipeline as user-app operations. Framework actors use the reserved sentinel `app_key = "__hassette__"`. The application must reject `"__hassette__"` as a user-app name via an `AppConfig` Pydantic field validator so it applies regardless of whether `app_key` is supplied via environment variable or direct instantiation. Framework-internal registrations must not be retired or deleted by app reconciliation: `"__hassette__"` must be excluded from the `AppHandler` reconciliation loop. Stale framework registrations are managed by the framework's own lifecycle, not by app reconciliation.

FR-5: The dispatch path must not use database registration state (presence or absence of a database ID) to determine whether to produce telemetry records. All dispatch paths must produce records regardless of registration timing.

FR-5a: The `InvokeHandler` and `ExecuteJob` command types must carry a `source_tier: str` field populated at the dispatch site (`bus_service.py` / `scheduler_service.py`), not derived from a database lookup in `CommandExecutor` or `TelemetryRepository`. `HandlerInvocationRecord` and `JobExecutionRecord` must gain a corresponding `source_tier: str` field. `TelemetryRepository.persist_batch` must include `source_tier` in the INSERT column list for both tables.

FR-5b: Records produced before registration completes must use `listener_id = None` / `job_id = None` (null FK) as the canonical pre-registration state. `HandlerInvocationRecord.listener_id` must be `int | None` and `JobExecutionRecord.job_id` must be `int | None`. No backfill is performed — if a handler fires before registration completes, the record persists as an orphan with null FK. The rationale: queue-scanning complexity, mutex coordination with the drain loop, and a new race condition for a window measured in milliseconds. The sentinel guard in `_persist_batch` must distinguish between null-FK (pre-registration orphan — persist normally) and `id == 0` (regression sentinel — drop and log REGRESSION). The pre-DB-ready buffering path requires that a session row is created as the first DB write during startup, before any queued framework execution records are flushed. `CommandExecutor` must not drain the write queue until a session ID is available. The session ID must be passed to framework-actor execution records at drain time, not at enqueue time.

FR-6: The ownership model uses the `app_key` column with a reserved sentinel value `"__hassette__"` for framework actors. Reconciliation already partitions by `app_key`, so framework actors get a reconciliation-exempt partition. Existing `GROUP BY app_key` queries work without modification.

### Query Correctness

FR-7: The recent errors query must return the N most recent errors across all error types (handler errors and job errors) in a single ordered result, not two independent result sets merged in application code.

FR-8: Dashboard queries must not exclude execution records whose parent registration has been deleted. Orphaned records must appear with appropriate labeling indicating the parent registration no longer exists. The `HandlerErrorRecord`, `JobErrorRecord`, and `SlowHandlerRecord` API response models must declare registration-derived fields (`app_key`, `handler_method`, `topic`, `job_name`) as `str | None`. The dashboard must render null values as "deleted handler" / "deleted job" (or equivalent placeholder) rather than failing.

FR-9: Dashboard summary queries must use consistent scoping:
- FR-9a: Activity count queries must use the same listener/job population as registration count queries (active records only, not including retired).
- FR-9b: The per-app health summary response model must document whether `handler_count` reflects all instances or only instance 0, and whether `total_invocations` aggregates all instances — and these must be consistent with each other.

### Write Pipeline Resilience

FR-10: When a batch of execution records fails to persist due to a transient database error, the records must be re-enqueued as a unit wrapped in an envelope type (e.g., `RetryableBatch`) that carries the retry count and the original batch. Individual record types are immutable and must not be modified. The maximum retry count default is 3. The shutdown flush path (`_flush_queue`) must understand the envelope type and drain all envelopes regardless of retry count. Record ordering is not guaranteed after re-enqueue — this is acceptable for append-only telemetry writes. Retry-exhausted records must be counted distinctly from overflow-dropped records.

FR-11: The write queue must have a bounded maximum size (default: 1000 — sufficient for 3 framework actors with heartbeat intervals ≥ 30s during a multi-minute DB init window). When the queue is full, the overflow policy is drop-with-logging: the record is discarded and an ERROR-level log entry is produced. Backpressure is not applied — telemetry is best-effort and event delivery must not stall.

### Endpoint Resilience

FR-12: All telemetry query endpoints must handle database unavailability gracefully, returning degraded responses (empty results or zero-value summaries) rather than unhandled 500 errors.

### Schema Integrity

FR-13: Status columns must be constrained to their valid value set at the database level.

FR-14: Duration columns must be constrained to non-negative values at the database level.

FR-15: The classification of dependency-injection failures must be determined at write time and stored as a persisted flag, not derived from string pattern matching in queries.

### FK Constraint Handling

FR-18: When a batch insert fails due to a foreign key constraint violation on `listener_id` or `job_id`, the affected record must be retried with the FK set to NULL and persisted as an orphan, rather than dropped. The design phase must verify whether `PRAGMA foreign_keys = ON` is set in the aiosqlite configuration; if FK enforcement is off (SQLite default), the edge case is a silent no-op and must be made explicit.

### Dashboard Filtering

FR-16: The dashboard must present user-app telemetry by default. Framework telemetry must be accessible but must not pollute the default user-app view.

FR-17: The specific UX for presenting framework telemetry (same feed with tags, separate section, toggle filter, or combination) is deferred to the design phase. The affordance for accessing framework telemetry must be visible on the default dashboard view (e.g., a count badge or expand control) — not hidden behind a URL change.

### Dashboard Observability

FR-19: When the write queue has dropped records due to overflow or max-retry exhaustion, the `/telemetry/status` endpoint must include a `dropped_records` count greater than zero. Overflow-dropped and retry-exhausted records must be counted separately. The count persists until the next restart.

### Migration Resilience

FR-20: The migration runner must detect partially-applied migrations at startup and either recover automatically (preferred for a destructive/recreatable DB) or emit a human-readable error message naming the exact recovery steps. A startup crash with a raw SQLite traceback is not acceptable.

### Reconciliation Safety

FR-21: The `"__hassette__"` sentinel `app_key` must be excluded from the `AppHandler` reconciliation loop. If `reconcile_registrations` is called with `app_key = "__hassette__"`, it must no-op (or raise) rather than processing framework registrations through the app reconciliation path. Framework actors that register `once=True` listeners must not be affected by the `once=True` deletion path in reconciliation.

## Edge Cases

1. **Framework actor fires before database is ready.** Framework actors that execute before `DatabaseService` is ready will have their records held in `CommandExecutor`'s write queue (initialized before the database wait in `__init__`). These records will be drained once `serve()` begins, after a session row has been created (FR-5b). The bounded queue size (FR-11, default 1000) is sufficient for pre-ready framework executions.

2. **Registration completes after first execution.** A user-app handler with debounce may fire before its database registration returns. The execution record is produced with `listener_id = None` (FR-5b). If registration completes before the record is flushed, the FK is backfilled; otherwise it persists as an orphan.

3. **Reconciliation deletes a registration with pending execution records in the write queue.** The write queue may contain records referencing a registration that reconciliation has just deleted. `ON DELETE SET NULL` nullifies existing child rows but does not affect new INSERTs referencing the deleted parent. If FK enforcement is enabled, these inserts will fail. FR-18 requires the write pipeline to detect FK constraint failures and retry with null FK.

4. **Write queue reaches capacity during a sustained database outage.** The overflow policy is drop-with-logging (FR-11). The overflow condition is observable via the `/telemetry/status` endpoint's `dropped_records` count (FR-19).

5. **Clock skew produces negative durations.** The schema rejects negative duration values at the database level (FR-14).

6. **`once=True` listener cleanup is deferred across multiple restarts.** When cleanup is deferred (due to unavailable session ID at reconciliation time), the deferred cleanup must execute on a subsequent startup rather than accumulating indefinitely. FR-21 ensures framework `once=True` listeners are not caught in the app reconciliation path.

## Test Infrastructure Requirements

AC-1 and AC-2 require the ability to register framework actors in the database and query the error feed in a single test. The following framework actors are in scope for testing:

- **Heartbeat job** (scheduled, repeating) — the primary framework scheduled job
- **WebSocket reconnection handler** (event listener) — fires on connection loss events
- **File watcher handler** (event listener) — fires on config file changes

`HassetteHarness` must be extended to support registering framework actors with `app_key = "__hassette__"` and `source_tier = "framework"`. A new integration test module is needed that combines live scheduler execution with queryable telemetry to verify AC-1, AC-2, and AC-11a/11b.

## Dependencies and Assumptions

1. **SQLite as the telemetry store.** The design assumes SQLite with WAL mode. CHECK constraints, nullable foreign keys with ON DELETE SET NULL, and UNION ALL queries must be supported.

2. **No production users.** The migration strategy is destructive — drop and recreate the database. This assumption must be revisited before any public release.

3. **Existing write queue architecture.** The CommandExecutor's async write queue pattern is retained and extended (retry, bounds) rather than replaced.

4. **Preact SPA dashboard.** The frontend is a Preact single-page application consuming JSON telemetry endpoints. UI changes are in scope but the specific UX is deferred to design.

5. **WAL snapshot lifetime.** The UNION ALL query required by FR-7 may hold WAL read snapshots open longer than the prior two-query approach. This should be profiled under sustained write pressure before any public release or before the HA Add-on milestone. Retention policy for `handler_invocations` and `job_executions` tables must be defined before 1.0.0 to bound UNION ALL scan cost.

6. **Session ordering.** A session row must be created as the first DB write during startup (FR-5b). The write queue drain depends on this ordering guarantee.

## Acceptance Criteria

AC-1: A framework-internal scheduled job that raises an exception produces an execution record visible in the dashboard error feed (when `source_tier` filter includes `'framework'`).

AC-2: A framework-internal event handler that raises an exception produces an invocation record visible in the dashboard error feed (when `source_tier` filter includes `'framework'`).

AC-3: The dashboard error feed displays the N most recent errors across both handler and job error types, correctly ordered by timestamp, regardless of the distribution between types.

AC-4: An execution record whose parent registration has been deleted (null FK) appears in dashboard queries with a "deleted handler" / "deleted job" label rather than being excluded or causing a validation error.

AC-5: A transient database write failure (simulated) results in the affected batch being retried end-to-end via the envelope mechanism — the retried records appear in the database after recovery, not silently dropped.

AC-6: All telemetry endpoints return degraded responses (not 500 errors) when the database is unavailable.

AC-7: The `status` column in execution tables rejects values outside the valid set at the database level.

AC-8: The `duration_ms` column rejects negative values at the database level.

AC-9: DI-failure classification is stored as a persisted flag and is not derived from string matching in any query.

AC-10: By default, the `/telemetry/dashboard/errors` endpoint returns only records where `source_tier = 'app'`. When the request includes a `source_tier` filter parameter (name, type, valid values, and error behavior defined in design phase), the endpoint returns records for the specified tiers.

AC-11a: Framework operations that execute before `DatabaseService` is ready have their execution records queued in `CommandExecutor`'s write queue and persisted once `serve()` starts processing the queue (after a session row is created). Verification: mock DB unavailability, confirm records accumulate, restore DB, confirm records in DB.

AC-11b: A user-app handler that fires before its DB registration completes produces an execution record in the database — either with the resolved FK (if backfill fires) or with a null FK (orphan). The record must not be silently dropped or logged as REGRESSION. Verification: gate registration with an `asyncio.Event`, fire the handler before the gate opens, open the gate, confirm the record exists.

AC-12: The write queue has a configured maximum size (default 1000); exceeding it produces an observable log entry and does not cause unbounded memory growth.

AC-13: When the write queue has dropped records due to overflow or max-retry exhaustion, the `/telemetry/status` endpoint includes a `dropped_records` count greater than zero. Overflow-dropped and retry-exhausted records are counted separately.

AC-14: The `source_tier` column rejects values outside the valid set (`'app'`, `'framework'`) at the database level.

AC-15: The migration runner detects a partially-applied migration at startup and either auto-recovers or emits a human-readable error message with recovery steps.

AC-16: The `source_tier` value on a persisted invocation record originates from the dispatch site (bus_service / scheduler_service), not from a database lookup in CommandExecutor or TelemetryRepository. Verification: confirm `InvokeHandler.source_tier` is populated at dispatch time.

AC-17: Attempting to register a user app with `app_key = '__hassette__'` raises a `ValueError` at the `AppConfig` field validator, before any DB write or scheduler registration occurs.

AC-18: The default dashboard view includes a visible affordance (count badge, section header, filter toggle, or equivalent control) that reveals framework telemetry without a URL change. The affordance is present even when there are zero framework records.

AC-19: After a full reconciliation cycle for all registered user apps, framework-internal listener and job registrations (`app_key = '__hassette__'`) are still present in the database with correct `source_tier = 'framework'` and have not been retired or deleted.

## Open Questions

*OQ-1 resolved: sentinel approach (`app_key = '__hassette__'`) selected — see FR-4, FR-6.*

1. **Dashboard UX for framework telemetry.** The specific presentation (same feed with tags, separate section, filter toggle, or combination) is deferred to design. The spec requires only that framework telemetry is accessible (FR-16, FR-17) and doesn't pollute the default view.

2. **Dispatch concurrency limits.** Challenge Finding 4 identified unbounded dispatch task count as an OOM vector. The specific backpressure mechanism (semaphore, queue bound, or both) is a design decision.

3. **Reconciliation scalability.** Challenge Finding 16 identified IN-clause degradation at high listener counts. Whether to use temporary tables, CTEs, or accept the current approach with monitoring is a design decision.

4. **FK enforcement pragma.** The design phase must verify whether `PRAGMA foreign_keys = ON` is set in the aiosqlite configuration. If FK enforcement is off (SQLite default), FR-18's retry-on-FK-violation path may be dead code — an application-level FK check may be needed instead.

5. **FR-5b backfill timing.** When does the backfill UPDATE fire — after `register_listener()` returns? After the write queue drains? Is there a race between the backfill UPDATE and concurrent reconciliation? The design phase must specify the exact timing and guard against races.
