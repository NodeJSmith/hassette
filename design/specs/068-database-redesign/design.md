# Design: Database Schema Redesign

**Date:** 2026-05-29
**Status:** archived
**Scope-mode:** hold
**Research:** design/specs/068-database-redesign/brief.md, design/research/2026-05-28-handler-listener-identity/research.md

## Problem

Every new telemetry feature requires changes in two places — one for handler invocations, one for job executions — because execution records are split across two near-identical tables. The duplication cascades through every layer: storage, queries, API responses, real-time messages, and frontend components. Adding a new column or query means writing the same code twice and keeping both sides in sync.

The cost is concrete: 11 open database issues, 3 of which (#648, #649, #650) require adding columns to both tables. The query service (1,187 lines) and repository (687 lines) are each ~40% pure duplication — mirrored pairs that do the same thing for handlers and jobs. #779 (listener deduplication) is directly blocked by friction in the registration and identity logic. #811 and #812 exist specifically because the duplicated modules are too large to work in comfortably. The migration tool adds to the burden: its auto-generation features are unused — all migrations are hand-written — but the dependency chain (3 transitive packages) remains.

Separately, listener identity relies on a computed key (handler method + topic + predicate summary) that is fragile and unlike any comparable framework. And each listener carries two IDs (one in-memory, one from the database) that can disagree, producing orphan records and filtering complexity on restart.

## Goals

- Reduce the telemetry code path from two parallel implementations to one — a new column like #648 becomes a single-table change instead of two
- Establish a stable, user-provided listener identity model that enables idempotent registration — unblocking #779
- Simplify startup by making registration synchronous with a single ID — zero orphan records, zero sentinel filtering
- Remove 3 transitive dependencies (migration tool + ORM + template engine) that are unused in production
- Reset the migration history so future schema changes (#648, #649, #650) land as clean single-file forward migrations

## Non-Goals

- Statistics aggregation table (#672) — additive migration on the new foundation
- Per-app retention and pin mechanism (#651) — additive
- Configurable database intervals (#564) — config-only, no schema impact
- DB seeding script (#854) — build after schema stabilizes
- Execution registry (#834) — dropped; 404 after retention purge is acceptable

## User Scenarios

### App Developer: Automation Author
- **Goal:** Register event handlers and scheduled jobs with reliable telemetry
- **Context:** Writing a hassette app in Python, calling `bus.on_state_change()` and `scheduler.run_every()`

#### Register a listener with a stable name

1. **Register a handler for a specific entity with a chosen name**
   - Sees: the registration call returns immediately — registration is complete on return
   - Decides: what name to give the listener (required)
   - Then: the listener is active and persisted with a single integer ID

2. **Restart the app**
   - Sees: the same listener re-registers with the same name
   - Decides: nothing — deduplication happens automatically by the identity key
   - Then: the existing record is updated, execution history is preserved

#### Register a listener without a name (error path)

1. **Call a registration method without providing `name`**
   - Sees: a clear error at call time explaining that `name` is required
   - Decides: what name to assign
   - Then: retries with a name and registration succeeds

#### View telemetry in the dashboard

1. **Open the handlers page**
   - Sees: a unified list of listeners and jobs with recent execution counts
   - Decides: which listener or job to inspect
   - Then: navigates to the detail page for that specific listener or job

2. **Check execution detail**
   - Sees: execution records with status, duration, errors — regardless of whether the source was a handler or a job
   - Decides: whether to investigate errors
   - Then: records are presented with a kind indicator distinguishing handlers from jobs

### Framework Maintainer: Hassette Developer
- **Goal:** Add new telemetry columns or query patterns without duplicating code
- **Context:** Implementing a new feature that needs execution metadata

#### Add a new execution column

1. **Write a forward migration (plain SQL file)**
   - Sees: a single `executions` table to ALTER
   - Decides: column name and type
   - Then: one migration file, one repository change, one query change — not two of each

## Functional Requirements

- **FR#1** Handler invocations and job executions are stored in a single unified table with a kind discriminator
- **FR#2** Registration records for listeners and scheduled jobs remain in separate tables with their distinct schemas
- **FR#3** Listener registration requires a user-provided name on all database-registered listeners
- **FR#4** Registering a listener with an existing identity key updates the existing record rather than creating a duplicate
- **FR#5** Database registration completes before a listener or job becomes routable — no asynchronous background registration
- **FR#6** Each listener and job has a single integer database ID as its only identifier — no secondary in-memory counter
- **FR#7** Schema migrations use the database's native version tracking instead of the current migration tool
- **FR#8** The current migration tool and its transitive dependencies are removed from the project
- **FR#9** Each migration is atomic — a crash mid-migration leaves the database at the previous version, not a partially-applied state
- **FR#10** The API returns execution records from a single interface with a kind indicator distinguishing handler and job executions
- **FR#11** Real-time execution notifications use a single unified message type with a kind indicator
- ~~**FR#12** The field currently named "app_key" renames to "owner_key" in the storage layer~~ — **WITHDRAWN 2026-05-29** (challenge review). `owner_key` was verified to be a synonym for `app_key`, not a broader concept: `Resource.app_key` (`resources/base.py:217`) already returns framework-prefixed keys and is documented as the telemetry identity key, and `source_tier` already discriminates app vs framework. The rename adds no semantic content at ~613 occurrences of cost. `app_key` is retained everywhere.
- ~~**FR#13** The "owner_key" rename propagates to API responses and real-time message payloads~~ — **WITHDRAWN** (see FR#12).
- ~~**FR#14** The "owner_key" rename propagates to the frontend~~ — **WITHDRAWN** (see FR#12).
- **FR#15** The "dropped before session ready" counter is removed from the execution pipeline
- **FR#16** The "dropped before session ready" API field, frontend status badge, and `dropped_no_session` column on the `sessions` table are removed from the new 001.sql schema
- **FR#17** The kind indicator is constrained to its two valid values at the storage level
- **FR#18** Session identity is not exposed in the API or frontend — time-based filtering is the only user-facing grain
- **FR#19** Known future columns (trigger mode, retry tracking, serialized arguments) are included in the initial schema to avoid immediate follow-up migrations
- **FR#20** Registering two different handlers with the same name and topic within a single app instance raises an error at registration time rather than silently overwriting

## Registration Errors

Two new exceptions in `hassette/exceptions.py`, both subclassing `HassetteError`:

**`ListenerNameRequiredError(HassetteError)`** — raised at call time when `name=` is omitted on a DB-registered listener. Raised by `Bus.on_state_change()` and siblings before any registration occurs.

```
ListenerNameRequiredError: Listener registration requires a name.

  handler: MyApp.on_light_change
  topic:   light.kitchen

Provide a stable name via the `name=` parameter:

  self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
```

**`DuplicateListenerError(HassetteError)`** — raised at call time when a second listener with the same `(name, topic)` is registered within the same app instance in the same session. Detected in-memory by the Bus before the DB write. Cross-session duplicates are handled by upsert (not an error).

```
DuplicateListenerError: A listener named "kitchen_light" is already registered for topic "light.kitchen".

  existing handler: MyApp.on_light_change
  duplicate handler: MyApp.on_light_change_v2

Use a different name for the second listener, or remove the first registration before re-registering.
```

Both exceptions include the handler method name and topic as instance attributes for programmatic access.

## Edge Cases

- **Name collision on registration:** Two listeners with the same identity key (owner, instance, name, topic) on restart — the upsert updates the existing record (correct deduplication). But within a single session, registering two different handlers with the same name and topic is a user error — the Bus detects this in-memory and raises `DuplicateListenerError` immediately rather than silently overwriting the first listener. Two listeners with the same name but different topics are distinct (topic is part of the key).
- **Concurrent registration across instances:** The write queue serializes all DB writes. Two app instances registering the same identity key concurrently result in last-write-wins via upsert — no error, no corruption.
- **Framework listeners without names:** Internal cancel-listeners bypass database registration entirely. Other framework listeners (state proxy, runtime query service) get explicit stable names.
- **Once-listeners under the new identity model:** Once-listeners require `name=` like all other DB-registered listeners. `DuplicateListenerError` does not apply to once-listeners within a session — the existing exemption in `check_listener_collision` survives, since once-listeners fire once and auto-unsubscribe (re-registering the same name is intentional, not a collision). On restart, a once-listener with the same identity key upserts the existing row, linking executions across sessions. `cleanup_stale_once_listeners` reconciliation uses `NOT EXISTS (SELECT 1 FROM executions WHERE listener_id = ...)` scoped to the current session — an upserted row with a new session_id is live and won't be cleaned up.
- **Handler-only fields on job rows:** Fields specific to handler execution (trigger context, trigger origin) are absent on job rows. The unified model makes these optional.
- **Bookmarked URLs after database reset:** Integer IDs reset on delete-recreate. Old bookmarks silently show empty results — acceptable (matches the existing behavior for all ID-based URLs after restart).
- **`ActivityFeedEntry.row_id` format change:** After unification, `row_id` switches from `'h-' || rowid` / `'j-' || rowid` (two separate sequences) to `execution_id` (UUID, globally unique from a single sequence). The `h-`/`j-` prefix convention in the activity feed query is removed — `execution_id` is already unique per row and available as a column. Frontend React keys use `execution_id` directly.
- **Migration failure mid-apply:** Each migration is atomic. A crash leaves the database at the previous version and retries on next startup.
- **Storage optimization on fresh databases:** A pre-migration step configures storage compaction settings before any schema creation — inherited from the current code.

## Acceptance Criteria

- **AC#1** All existing tests pass after adaptation to the new schema — maps to FR#1, FR#2, FR#5, FR#6
- **AC#2** End-to-end tests pass for the unified execution interface and real-time notifications — maps to FR#10, FR#11
- **AC#3** Frontend manual verification: handlers page shows unified list, detail pages load, activity feed updates in real time — maps to FR#10, FR#11
- **AC#4** Demo script produces expected database structure: unified execution table with kind indicator, native version tracking set correctly, no legacy migration metadata — maps to FR#1, FR#7, FR#9
- **AC#5** Static analysis and type checking pass with zero errors — global quality gate across all FRs (originally mapped to the withdrawn FR#12–14; retained as the overall pyright/build gate)
- **AC#6** Registering a listener without a name raises a clear error at call time — maps to FR#3
- **AC#7** A registered listener has a valid integer database ID immediately on return — no deferred registration to await — maps to FR#5, FR#6
- **AC#8** The migration tool and its transitive dependencies are no longer listed as project dependencies — maps to FR#8
- ~~**AC#9** No references to the old field name ("app_key") remain in production source code~~ — **WITHDRAWN 2026-05-29** (challenge review). The `app_key`→`owner_key` rename was dropped; `app_key` is the retained name. See withdrawn FR#12.
- **AC#10** No references to the removed session-readiness counter remain in production code — maps to FR#15, FR#16
- **AC#11** The kind indicator rejects values other than its two valid options at the storage level — maps to FR#17
- **AC#12** Known future columns are present in the initial schema without requiring a follow-up migration — maps to FR#19
- **AC#13** Session identity fields are absent from API responses and the frontend — maps to FR#18
- **AC#14** Registering two handlers with the same name and topic in one app raises a clear error naming both the duplicate name and the topic — maps to FR#20

## Key Constraints

- The upsert `ON CONFLICT` target must exactly match the unique index expression — any divergence causes SQLite to silently INSERT instead of UPDATE.
- `_RETENTION_TABLES` and parent-guard DELETE queries in `database_service.py` hard-code table names — these must be updated to reference the unified `executions` table with `kind` discriminator filters.
- `BusService` and `SchedulerService` must both declare `depends_on: [DatabaseService]` to guarantee DB readiness before synchronous registration.
- Each registration is a sequential `execute() + RETURNING` through the write queue (~1ms each). No batching needed — 20 listeners adds ~20ms to startup, negligible compared to HA connection and state loading.

## Dependencies and Assumptions

- **SQLite PRAGMA user_version:** Built-in, no external dependency. Standard pattern for embedded SQLite (Android, Firefox, Chromium).
- **aiosqlite:** Already a dependency — the write queue and `database_service.submit()` mechanism is unchanged.
- **openapi-typescript:** Already in the frontend build — type regeneration is mechanical.
- **Assumption:** Delete-recreate on schema version mismatch is acceptable. Telemetry data is ephemeral (7-day default retention). No data migration needed.
- **Assumption:** Startup cost of synchronous registration is negligible. N listeners × ~1ms per sequential write-queue round-trip. A 20-listener app adds ~20ms to startup.

## Architecture

### Schema

The unified `executions` table has two nullable FK columns — `listener_id` (references `listeners`) and `job_id` (references `scheduled_jobs`) — exactly one non-null per row, enforced by both the repository and a schema CHECK: `CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`. The `kind` CHECK and the FK mutex CHECK are both set in the initial 001.sql — the SQLite ALTER TABLE limitation that motivates the no-CHECK rule does not apply to constraints set at table creation. The `kind` column carries a `CHECK (kind IN ('handler', 'job'))` constraint — the single exception to the no-CHECK rule, justified because `kind` is a fixed two-value discriminant that will never evolve.

Handler-only columns (`trigger_context_id`, `trigger_origin`) are nullable — NULL for job rows.

New columns baked in from day one to avoid future ALTER TABLE:
- `trigger_mode TEXT` (#648) — how the execution was triggered. Values: `'event'`, `'schedule'`, `'manual'`, `'retry'`. Nullable (NULL until the feature that populates it ships).
- `retry_count INTEGER NOT NULL DEFAULT 0`, `attempt_number INTEGER NOT NULL DEFAULT 1` (#649) — retry tracking per execution.
- `args_json TEXT NOT NULL DEFAULT '[]'`, `kwargs_json TEXT NOT NULL DEFAULT '{}'` (#650) — serialized arguments captured at execution time. Matches the existing columns on `scheduled_jobs`.

Index plan for the unified table (10 current indexes → 6):
- `idx_exec_listener_time` on `(listener_id, execution_start_ts DESC) WHERE listener_id IS NOT NULL`
- `idx_exec_job_time` on `(job_id, execution_start_ts DESC) WHERE job_id IS NOT NULL`
- `idx_exec_status_time` on `(status, execution_start_ts DESC)`
- `idx_exec_time` on `(execution_start_ts)` — retention cleanup
- `idx_exec_session` on `(session_id)`
- `idx_exec_source_tier_time` on `(source_tier, execution_start_ts DESC)`

### Listener Identity

Natural key: `(app_key, instance_index, name, topic)`. `name` is `NOT NULL`. `handler_method` exits the key (stays as display-only metadata). `predicate_description` and `human_description` stay as metadata columns. The upsert conflict target matches this key exactly. The current unique index filter `WHERE once = 0` is removed — once-listeners participate in upsert deduplication so that executions across multiple sessions link to the same listener row. The `once` column stays as a behavioral flag but exits the index.

Framework services that already provide names: ServiceWatcher (5), AppHandler (1), SessionManager (1). Need names added: StateProxy (1), RuntimeQueryService (~6). Cancel-listeners are exempt (bypass DB registration entirely).

The `scheduled_jobs` natural key (`app_key, instance_index, job_name`) is already name-based and does not change — `job_name` auto-generates from the callable name if not provided by the user. The `log_records` table (added in migration 009) is unaffected by the redesign and carries over into the new 001.sql unchanged.

### Synchronous Registration

`BusService.add_listener()` awaits `database_service.submit()` inline instead of spawning a background task. Return type changes from `asyncio.Task[None]` to `int` (the db_id). `BusService` and `SchedulerService` both gain `depends_on: [DatabaseService]`. Each registration is a sequential `execute() + RETURNING` through the write queue — no `executemany` (SQLite's `executemany` doesn't support per-row `RETURNING`). Typical startup cost: ~1ms per listener, ~20ms for a 20-listener app.

`SchedulerService` follows the same pattern — job registration awaited before enqueuing to the scheduler heap. This eliminates the window where a job fires with `db_id=None`.

`RegistrationTracker` (entire class), `drain_framework_registrations()`, `await_registrations_complete()` barriers, and `Subscription.registration_task` are all removed.

The `_listener_meta`/`_job_meta` in-memory dicts in `RuntimeQueryService` (populated as a side-effect of `CommandExecutor.register_listener/job()`) are also removed. These existed to enrich WS completion messages with `app_key` without a DB read — the completion event payloads intentionally excluded ownership info to decouple CommandExecutor from the web layer. Under synchronous registration, the decoupling cost outweighs the benefit: the Listener/ScheduledJob object is guaranteed alive and in-memory when its handler fires, so `app_key` and `instance_index` can be added directly to the completion event payloads (`InvocationCompletedPayload`, `ExecutionCompletedPayload`). This eliminates the cache, the registration side-effects in CommandExecutor, and the pruning logic — without adding DB reads to the broadcast path.

### Migration Runner

Replace Alembic with `PRAGMA user_version` + ~35-line runner. The runner:
1. If fresh database (`user_version = 0`): opens a raw `sqlite3.Connection`, checks/sets `auto_vacuum = INCREMENTAL`, closes it. `PRAGMA auto_vacuum` cannot be set inside a transaction — the separate connection ensures no transaction is active. First-run only.
2. Reads `PRAGMA user_version`
3. Iterates sorted `.sql` files from `current_version + 1` to target
4. Each migration runs inside `BEGIN IMMEDIATE` / `COMMIT` with `PRAGMA user_version = N` as the final statement

The mismatch logic in `_handle_schema_version()` survives — integer comparison replaces string comparison. Delete-recreate behavior on downgrade is unchanged.

### Query Service Module Structure

The current `telemetry_query_service.py` (1,187 lines) is projected at ~1,100 lines post-merge — still above the 800-line cap. Split into focused modules under `core/telemetry/`:

- `core/telemetry/query_service.py` — the `TelemetryQueryService` class (initialization, DB access, `execute()` context manager) + re-exports for backward compatibility. ~100 lines.
- `core/telemetry/registration_queries.py` — `get_listener_summary`, `get_job_summary`, `get_all_listeners_summary`, `get_all_jobs_summary`, `get_slow_handlers`. Per-registration queries. ~350 lines.
- `core/telemetry/execution_queries.py` — unified `get_executions` (replaces `get_handler_invocations` + `get_job_executions`), `get_app_recent_activity`, `get_per_app_activity_buckets`, `get_per_app_last_errors`, `get_recent_invocations_1h*`, `check_execution_predates_retention_cutoff`. ~350 lines.
- `core/telemetry/summary_queries.py` — `get_app_health_aggregates`, `get_all_app_summaries`, `get_session_list`, `get_log_records*`. ~200 lines.

Helper functions (`_source_tier_clause`, `_since_clause`, `_row_to_dict`, `_build_app_summaries`, `AppHealthAggregates`) move to `core/telemetry/helpers.py`.

The repository (`telemetry_repository.py`, 687 → ~620 lines) stays as one file — it's under the cap after the merge.

**Response models that stay split:** `AppHealthSummary` retains its split fields (`total_invocations`/`total_executions`, `total_errors`/`total_job_errors`, `total_timed_out`/`total_job_timed_out`) — aggregation queries reconstruct by kind using the unified table. This is a deliberate API stability choice: 8+ frontend files reference these fields separately, and merging them would expand the blast radius without reducing query complexity.

### Reconciliation and Retention

Reconciliation (post-init cleanup of stale registrations) and retention (hourly age-based cleanup of execution records) both reference execution tables by name in their SQL. The logic is unchanged — only the table name changes from `handler_invocations`/`job_executions` to `executions`.

Reconciliation's `EXISTS`/`NOT EXISTS` subqueries use FK columns (`listener_id`, `job_id`) to scope correctly — no `kind` filter needed. For example, the "delete stale listeners with no history" query becomes `NOT EXISTS (SELECT 1 FROM executions WHERE listener_id = listeners.id)` instead of `NOT EXISTS (SELECT 1 FROM handler_invocations WHERE listener_id = listeners.id)`. The partial indexes (`idx_exec_listener_time WHERE listener_id IS NOT NULL`, `idx_exec_job_time WHERE job_id IS NOT NULL`) cover these subqueries.

Retention cleanup: `_RETENTION_TABLES` reduces from three entries (`log_records`, `handler_invocations`, `job_executions`) to two (`log_records`, `executions`). The parent-guard DELETE queries for retired listeners/jobs update the same way — table name only, FK scoping unchanged.

### API Unification

Combined list endpoint `/telemetry/executions` with `kind` query param and discriminated union response. Detail endpoints use resource-nested paths: `/telemetry/listener/{id}/executions` and `/telemetry/job/{id}/executions` (renamed from `/telemetry/handler/{id}/invocations` and `/telemetry/job/{id}/executions`). All three share the same query function with different FK filters. The existing Pydantic discriminated union pattern (`Annotated[... | ..., Field(discriminator="type")]` in `WsServerMessage`) is reused.

Unified WebSocket message: `execution_completed` with a discriminated union payload. Struct layout:

```python
class ExecutionCompletedData(BaseModel):
    kind: Literal["handler", "job"]
    app_key: str
    instance_index: int
    status: str
    duration_ms: float
    error_type: str | None = None
    listener_id: int | None = None   # set when kind="handler"
    job_id: int | None = None        # set when kind="job"

class ExecutionCompletedWsMessage(BaseModel):
    type: Literal["execution_completed"]
    data: list[ExecutionCompletedData]
    timestamp: float
```

Frontend predicate closures must narrow by `kind` before accessing kind-specific fields: `e.kind === 'handler' && e.listener_id === targetId`. The merged signal replaces both `invocationCompleted` and `executionCompleted` — predicates that previously accessed `e.listener_id` on a handler-only signal must add the `kind` guard to avoid `undefined` comparisons on job rows.

### Frontend

- Type regeneration via `export_schemas.py --types` (mechanical)
- Two WS signals merge to one; two `case` branches merge
- `/listener/:id` and `/job/:id` path-based routing replaces `h-`/`j-` prefix; `handler-ids.ts` deleted
- `droppedNoSession` signal and badge removed from status bar

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `handler_invocations` + `job_executions` tables | Unified `executions` table | Remove old tables in migration 001 |
| `_inv_insert_params()` + `_job_insert_params()` in `telemetry_repository.py` | Single `_execution_insert_params()` | Delete both, write one |
| Mirrored query pairs in `telemetry_query_service.py` | Single parameterized queries with FK/`kind` filter | Merge each pair |
| `HandlerInvocation` + `JobExecution` models in `telemetry_models.py` | Unified `Execution` model with `kind` discriminator | Delete both, write one |
| `InvocationCompletedWsMessage` + `ExecutionCompletedWsMessage` in `web/models.py` | Single `ExecutionCompletedWsMessage` with discriminated union payload | Delete both, write one |
| Dual-list logic in `command_executor.py` (`_build_record`, `_persist_batch`, `_drain_and_persist`, `RetryableBatch`) | Single-list equivalents | Merge dual branches |
| `src/hassette/migrations/` directory (14 files) + `alembic.ini` | Plain `.sql` files + ~35-line PRAGMA user_version runner | Delete directory, write runner |
| Alembic imports + 3 methods in `database_service.py` | PRAGMA-based version check | Rewrite 3 methods, delete 5 imports |
| `RegistrationTracker` class (`core/registration_tracker.py`) | Nothing — synchronous registration makes it unnecessary | Delete file |
| `Subscription.registration_task` field | Nothing — registration complete on return | Remove field |
| `_listener_id_seq` (`itertools.count`) in `bus/listeners.py` | DB row ID as the single identifier | Delete counter |
| `handler-ids.ts` (frontend) | Path-based routing (`/listener/:id`, `/job/:id`) | Delete file |
| `dropped_no_session` counter + API field + frontend badge | Nothing — dead code after synchronous registration | Delete from all layers |
| `persist_batch_with_fk_fallback` + `_insert_row_with_fk_fallback` in `telemetry_repository.py` | Rewritten for unified `executions` table with `kind` discriminator | Rewrite — hardcoded `handler_invocations`/`job_executions` table names |
| `_listener_meta` + `_job_meta` dicts in `RuntimeQueryService` | `app_key` and `instance_index` added directly to completion event payloads — object guaranteed in-memory under synchronous registration | Delete dicts, registration side-effects in `CommandExecutor`, and pruning logic in `RuntimeQueryService` |

## Migration

Delete-recreate: the migration chain resets to 001. Old databases with any Alembic-era schema version trigger the existing delete-recreate path (delete DB files including WAL/SHM, recreate on fresh migrations). No data migration — telemetry is ephemeral with 7-day default retention.

Rollback: a user downgrading to an older version sees a schema version mismatch and gets the same delete-recreate. Telemetry history is lost on downgrade — same as today.

The `alembic_version` table is not created in the new schema. Its absence plus the `PRAGMA user_version` value is how the runner detects "new schema."

## Convention Examples

### SQL query builder pattern — parameterized fragment + bind params

**Source:** `src/hassette/core/telemetry_query_service.py:59-76`

```python
def _source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
    match source_tier:
        case "all":
            return ("", {})
        case "app" | "framework":
            return (f"AND {alias}.source_tier = :source_tier", {"source_tier": source_tier})
        case _ as unreachable:
            assert_never(unreachable)
```

New query helpers for `kind` filtering should follow this pattern: return `(fragment, params)` tuples that callers splice into SQL strings.

### INSERT param builder — dict-from-record

**Source:** `src/hassette/core/telemetry_repository.py:27-52`

```python
def _inv_insert_params(record: HandlerInvocationRecord) -> dict[str, Any]:
    return {
        "listener_id": record.listener_id,
        "session_id": record.session_id,
        "execution_start_ts": record.execution_start_ts,
        # ... all columns
        "execution_id": record.execution_id,
    }
```

The unified `_execution_insert_params()` should follow this pattern: flat dict, one key per column, booleans converted to int for SQLite.

### Service class with `depends_on`

**Source:** `src/hassette/core/command_executor.py:67-83`

```python
class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
    )
```

`BusService` will gain `depends_on: [DatabaseService]` following this exact pattern.

### Discriminated union WS message

**Source:** `src/hassette/web/models.py:235-268`

```python
class InvocationCompletedData(BaseModel):
    listener_id: int
    app_key: str
    instance_index: int
    status: InvocationStatus
    duration_ms: float
    error_type: str | None = None

class InvocationCompletedWsMessage(BaseModel):
    type: Literal["invocation_completed"]
    data: list[InvocationCompletedData]
    timestamp: float
```

The unified `ExecutionCompletedWsMessage` follows this pattern but with a `kind` discriminator on the data payload.

### DB_ERRORS catch pattern

**Source:** `src/hassette/web/CLAUDE.md`

```python
from hassette.web.dependencies import DB_ERRORS

try:
    result = await telemetry.some_query()
except DB_ERRORS:
    LOGGER.warning("Failed to fetch ...", exc_info=True)
    response.status_code = 503
    return []
```

All new/modified telemetry route handlers use this pattern for graceful degradation.

## Alternatives Considered

**Keep separate tables, add views:** Create a `CREATE VIEW executions AS SELECT ... UNION ALL SELECT ...` to provide a unified read interface while keeping separate write tables. Rejected: views in SQLite cannot be indexed, and the duplication in the write path (repository, command executor) remains.

**Alembic with `render_as_batch`:** SQLite's ALTER TABLE limitations can be worked around with Alembic's batch mode. Rejected: batch mode is still Alembic — the dependency chain stays, and all migrations are already hand-written SQL that doesn't benefit from Alembic's code generation.

**Keep `handler_method` in the natural key:** Safer deduplication without requiring `name=`. Rejected: prior art research (6 frameworks surveyed) unanimously supports user-provided stable keys. Computed keys based on method names are fragile and unique to hassette.

**Single FK column (`owner_id`) with kind routing:** One FK column instead of two nullable FKs. Rejected: two nullable FKs are self-documenting, preserve the existing reconciliation query structure, and don't require kind-aware JOIN logic.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/bus/test_bus_contract.py` — tests that `await sub.registration_task`; update to verify `sub.listener.db_id` is immediately available
- `tests/unit/bus/test_bus_public_private_split.py` — asserts `registration_task` existence/behavior; remove or adapt
- `tests/unit/bus/test_duration_hold.py` — cancel-listener tests that check pre-resolved Future; simplify
- `tests/unit/bus/test_listeners.py` — `Subscription` field assertions; update for removed fields
- `tests/unit/core/test_scheduler_service_barrier.py` — registration barrier tests; remove (barrier deleted)
- `tests/unit/core/test_command_executor.py` — dual-list persist logic, sentinel filtering; update for unified records
- `tests/unit/core/test_telemetry_repository.py` — dual table INSERT/upsert tests; update for unified table
- `tests/unit/core/test_telemetry_query_service.py` — mirrored query tests; merge pairs
- `tests/system/conftest.py:262` — uses `sub.listener.db_id is not None` as gate; simplify (always set)
- `tests/e2e/` — frontend tests referencing handler/job endpoints by URL; update paths
- `tests/unit/cli/test_commands_listener.py`, `tests/unit/cli/test_commands_job.py` — mock the renamed detail endpoint and the unified `Execution` response shape (T17)

### New Test Coverage

- **FR#1:** Verify unified execution table accepts both handler and job rows with correct FK constraints (unit)
- **FR#3:** Verify registering a listener without a name raises a clear error (unit)
- **FR#4:** Verify re-registration on identity key conflict updates metadata, not duplicates (unit)
- **FR#5:** Verify listener database ID is set before handler is routable (integration)
- **FR#7:** Verify migration runner applies migrations in order and sets version atomically (unit)
- **FR#9:** Verify a simulated crash mid-migration leaves the database at the previous version (unit)
- **FR#10:** Verify unified execution interface returns responses with kind indicator (integration)
- **FR#11:** Verify unified real-time notification with kind field (e2e)
- **FR#4 (structural):** Verify upsert conflict target matches the unique index definition by querying `sqlite_master` and asserting the expressions match verbatim (unit) — catches drift that behavioral tests miss
- **FR#17:** Verify kind constraint rejects invalid values at the storage level (unit)
- **FR#19:** Verify new columns exist in the initial schema (unit)
- **FR#20:** Verify duplicate name+topic registration within one app raises an error (unit)

### Tests to Remove

- Registration barrier tests in `test_scheduler_service_barrier.py` — the barrier mechanism is deleted
- Any tests for `registration_task` completion signal semantics — the field is removed
- Tests for sentinel=0 filtering in command_executor — the sentinel architecture is eliminated
- Tests for session-readiness counter behavior — the counter is removed (FR#13, FR#14)

## Documentation Updates

- `docs/pages/core-concepts/bus/handlers.md` — remove `registration_task` and `db_id` from reference table; update registration guidance ("registration is complete when `on_state_change()` returns"); add `name=` parameter documentation
- `docs/pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py` — remove `await sub.registration_task` patterns
- `docs/pages/core-concepts/internals.md` — update database section for PRAGMA user_version, unified executions table
- `CLAUDE.md` — update "Bus" description to mention `name=` required; update "Resource Hierarchy" for `BusService.depends_on`; note `Subscription` field changes
- API reference docstrings on `Bus.on_state_change()`, `Bus.on()`, etc. — document `name` parameter as required

## Impact

### Changed Files

**Shared/cross-cutting (higher risk):**
- `core/database_service.py` — migration runner replacement, retention table refs
- `core/command_executor.py` — unified record building, persist logic, sentinel removal
- `core/bus_service.py` — synchronous registration, `depends_on` addition
- `core/scheduler_service.py` — synchronous registration, `depends_on` addition
- `web/models.py` — unified WS messages
- `pyproject.toml` — dependency removal

**Repository/query layer (bulk of the change):**
- `core/telemetry_repository.py` — unified INSERT, persist, reconciliation
- `core/telemetry_query_service.py` — merged query pairs
- `core/telemetry_models.py` — unified Execution model

**API/routes:**
- `web/routes/telemetry.py` — unified endpoint
- `web/telemetry_helpers.py` — minor (metadata display)
- `web/mappers.py` — minor (field name updates)

**CLI:**
- `cli/commands/listener.py` — import unified `Execution` (was `HandlerInvocation`), detail endpoint `/telemetry/handler/{id}/invocations` → `/telemetry/listener/{id}/executions`
- `cli/commands/job.py` — import unified `Execution` (was `JobExecution`), unified response shape

**Bus/scheduler internals:**
- `bus/listeners.py` — remove `_listener_id_seq`, remove `registration_task` from Subscription
- `bus/bus.py` — remove task capture in `_on_internal()`
- `bus/invocation.py` — eager db_id read
- `bus/duration_hold.py` — simplified cancel-listener
- `scheduler/classes.py` — remove `JOB_ID_SEQ`, `db_id` field, `mark_registered()`
- `core/registration_tracker.py` — delete file
- `core/app_lifecycle_service.py` — remove barrier awaits
- `core/core.py` — remove framework drain call

**Frontend:**
- `use-websocket.ts` — merged signals
- `create-app-state.ts` — merged signal, remove `droppedNoSession`
- `listener-detail.tsx`, `job-detail.tsx` — endpoint path updates
- `recent-activity-section.tsx` — React key switches to `execution_id` (row_id format change)
- `handlers-tab.tsx` — path-based routing
- `handler-rows.ts` — updated types
- `handler-ids.ts` — delete file
- `endpoints.ts` — unified endpoint paths
- `query-keys.ts` — merged cache keys
- `use-telemetry-health.ts`, `alert-banner.tsx`, `status-bar.tsx`, `diagnostics.tsx` — remove `droppedNoSession`
- `palette-items.ts` — updated navigation URLs
- `generated-types.ts`, `ws-types.ts` — regenerated (mechanical)

**Deleted:**
- `src/hassette/migrations/` — entire directory (14 files)
- `alembic.ini`
- `core/registration_tracker.py`
- `frontend/src/utils/handler-ids.ts`

**New:**
- Migration runner module (~35 lines)
- `migrations/001.sql` — unified schema DDL

### Behavioral Invariants

- **Write queue single-writer contract:** All DB writes still flow through `database_service.submit()` → `_db_write_worker`. The serialization guarantee is unchanged.
- **Retention cleanup:** Hourly cleanup and size failsafe continue to work — only table references change.
- **Router dispatch:** `Router.add_route()` / `dispatch()` are unchanged. Event routing is not affected by the DB changes.
- **CLI commands:** `hassette status`, `hassette listener`, `hassette log` — output format may change but commands must continue working.
- **`source_tier` filtering:** The column and `_source_tier_clause` helper survive. Framework listeners are still filtered from user-facing views.
- **Session heartbeat and crash recording:** The `sessions` table and its lifecycle are unchanged internally.

### Blast Radius

- **All hassette apps:** `name=` required on `bus.on_state_change()` and siblings is a breaking API change. Every user app needs updating.
- **Frontend:** Every telemetry-consuming component needs type/path updates. The type regeneration pipeline catches most issues, but WS predicate closures and dynamic dict keys need manual attention.
- **Docker image:** Dependency removal (alembic/sqlalchemy/mako) reduces image size.
- **Documentation:** Handlers page, internals page, CLAUDE.md, API reference docstrings all need updates.
- **Test suite:** ~10 test files need adaptation, ~4 test files/classes get deleted or substantially simplified.
- **Failure mode shift:** Registration errors (missing `name=`, duplicate name+topic, DB write failure) now fail app startup rather than degrading silently. Previously, a DB write failure logged a warning and the listener ran without telemetry. Under synchronous registration, registration errors propagate out of `on_initialize()` and mark the app FAILED.

## Open Questions

None — all questions resolved during brief exploration, challenge review, and design review.

<!-- Gap check 2026-05-29: production code gaps included — events/hassette.py (payload fields) → T06 Step 1, events/__init__.py (re-exports) → T06 Step 1, runtime_query_service.py (meta dict removal) → T06 Step 3, session_manager.py (dropped_no_session UPDATE) → T05 Step 2, test_utils/web_mocks.py (get_drop_counters mock) → T05 Step 5. ~15 test file gaps → T04 Step 7, T06 Step 5, T08 Step 7, T09 Step 6, T13. -->
<!-- Design-review fix 2026-05-29: CLI blast radius (cli/commands/listener.py, job.py — deleted HandlerInvocation/JobExecution models + renamed detail endpoint) was untracked; now owned by T17 (depends T07, T11; gates into T16). Listener natural-key drift guard added across T03 (in-memory key) + T08 (DB index structural test). -->
<!-- Challenge 2026-05-29: app_key→owner_key rename DROPPED. Critics verified owner_key is a synonym for app_key (Resource.app_key already returns framework-prefixed keys and is documented as the telemetry identity key; source_tier already discriminates app vs framework). T01 deleted; FR#12/13/14 and AC#9 withdrawn; app_key retained across all layers. Natural key is (app_key, instance_index, name, topic). Tasks renumbered set: T02–T17 (no T01). -->
