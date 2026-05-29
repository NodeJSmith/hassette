# Brief: Database Schema Redesign

**Date:** 2026-05-28
**Status:** explored

## Idea

Rewrite hassette's telemetry database schema to unify the duplicated execution tables, demote sessions to internal-only, fold in pending schema enhancements, replace Alembic with `PRAGMA user_version` for migrations, and redesign listener identity around user-provided names. The migration chain resets to a single 001 (one final delete-recreate), after which all future schema changes use proper forward migrations instead of delete-recreate.

**Forcing function:** Implementing `if_exists` for listener registration (#779) is blocked by friction in the database registration and deduplication logic. The current schema shape contributes to that friction.

## Key Decisions Made

- **Unified executions table.** `handler_invocations` and `job_executions` merge into a single `executions` table with a `kind` discriminator. Registration tables (`listeners`, `scheduled_jobs`) stay separate — their schemas are genuinely different. FK design: two nullable columns — `listener_id` (references `listeners`) and `job_id` (references `scheduled_jobs`) — exactly one non-null per row, enforced by the repository. This preserves the existing reconciliation query structure (same FK names, only the table name changes).

- **Sessions become internal-only.** The `sessions` table stays for crash recording, heartbeat, and drop counters, but `session_id` is not exposed in the API or frontend. No sessions endpoint, no session-based filtering. Time-based filtering is the only user-facing grain. `session_id` remains `NOT NULL` in the unified `executions` table — the session row is inserted synchronously before any app `on_initialize` runs, extending the synchronous registration invariant.

- **Integer PK + UUID column.** Auto-increment `id` as primary key, `execution_id` as a unique indexed UUID column. Both are needed: the UUID is assigned at invocation time (pre-INSERT) and stamped on log records via `CURRENT_EXECUTION_ID` context var for log correlation — the integer PK isn't available until after the DB INSERT. Best SQLite write locality.

- **Discriminated union API.** The unified API returns `kind: Literal["handler"]` or `kind: Literal["job"]` on execution records, using the same Pydantic discriminated union pattern already used for WebSocket messages. openapi-typescript generates clean TypeScript unions from this.

- **#834 (execution registry) dropped.** 404 after retention purge is acceptable — matches HA's behavior for traces and history. No tombstone table needed.

- **Validation moves to application layer.** No inline CHECK constraints in the schema (they prevent ALTER TABLE in SQLite). All validation in Pydantic models and repository code. Schema contains columns, indexes, and foreign keys only. **Exceptions** (both in the initial 001.sql, where ALTER TABLE limitations don't apply): (1) `CHECK (kind IN ('handler', 'job'))` on the unified `executions` table — `kind` is a fixed two-value discriminant that will never evolve; without this, a write-path bug storing the wrong `kind` passes insertion and surfaces as a 500-class Pydantic validation error at read time. (2) `CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)` — enforces the FK mutex at the storage level alongside the repository.

- **Migration chain resets to 001.** The new schema is migration 001. Old databases get one final delete-recreate. After this, real forward migrations for all future changes.

- **Replace Alembic with `PRAGMA user_version`.** Alembic's value-adds (auto-generation, ORM diffing, branching, downgrades) are unused — all migrations are hand-written SQL. SQLite's built-in `user_version` pragma + a ~35-line runner replaces the entire Alembic + SQLAlchemy + Mako dependency chain. This is the standard pattern for embedded SQLite (Android, Firefox, Chromium). See research notes below.

- **REST endpoint strategy.** Detail endpoints (`/telemetry/handler/{id}/invocations`, `/telemetry/job/{id}/executions`) merge into a unified `/telemetry/executions` endpoint with `kind` query param and discriminated union response. Frontend `endpoints.ts` paths and `query-keys.ts` cache keys need updating.

- **Frontend routing: `/listener/:id` and `/job/:id` replace `h-`/`j-` prefix convention.** The detail pages are already separate components (`listener-detail.tsx`, `job-detail.tsx`), so the URL routing should reflect that instead of encoding kind in a custom prefix. `handler-ids.ts` and `parseHandlerId` get deleted. Combined list keys become `listener-${id}` / `job-${id}` (plain string concat).

- **`app_key` renames to `owner_key`.** Lands as a dedicated first commit via mechanical codemod, before any schema changes — the ~613 occurrences span every layer and would obscure structural diffs if bundled. Full breaking change across all layers: DB columns, REST response models (10+ models in `models.py`), WS payload fields (`InvocationCompletedData`, `ExecutionCompletedData`), and frontend. Requires explicit updates to: the dynamic dictionary key in `use-websocket.ts:113` (`msg.data.app_key` → `msg.data.owner_key`), the structural cast in `recent-activity-section.tsx:126-127` (not caught by TypeScript type regeneration), and `create-app-state.ts` signal names. (#739)

- **Index plan for the unified `executions` table.** Current schema has 5 indexes per execution table (10 total). The unified table reduces to 6:
  - `idx_exec_listener_time` on `(listener_id, execution_start_ts DESC) WHERE listener_id IS NOT NULL` — partial index, skips job rows
  - `idx_exec_job_time` on `(job_id, execution_start_ts DESC) WHERE job_id IS NOT NULL` — partial index, skips listener rows
  - `idx_exec_status_time` on `(status, execution_start_ts DESC)` — merged, covers both kinds
  - `idx_exec_time` on `(execution_start_ts)` — merged, used by retention cleanup
  - `idx_exec_session` on `(session_id)` — merged
  - `idx_exec_source_tier_time` on `(source_tier, execution_start_ts DESC)` — merged

  No dedicated `kind` index — queries filtering by kind use the partial FK indexes instead (`listener_id IS NOT NULL` ≡ `kind = 'handler'`). FK indexes stay separate because the nullable columns are distinct. Partial indexes on the FKs skip NULL entries (~50% of rows), keeping the index lean.

- **New columns baked into the initial schema.** `trigger_mode` (#648), `retry_count`/`attempt_number` (#649), `args_json`/`kwargs_json` (#650) land in the unified executions table from day one, avoiding future ALTER TABLE for known requirements.

- **Upsert conflict target must match the natural key index exactly.** When `name` becomes `NOT NULL`, the current `COALESCE(name, human_description, '')` expression in both the unique index and the repository's `ON CONFLICT` clause becomes dead code. Both must update to the new key expression in the same commit — any divergence causes SQLite to silently INSERT instead of UPDATE, producing duplicate rows on restart.

- **Listener identity redesign: `name` becomes required.** Prior art research (Django dispatch_uid, Temporal Workflow ID, Celery task names, AppDaemon) confirms that user-provided stable keys are the industry standard for idempotent registration. The current computed identity (predicate summary in the natural key) is fragile and not used by any comparable framework. `name=` becomes required on all DB-registered listeners (both app-tier and framework-tier), making the natural key `(owner_key, instance_index, name, topic)`. Cancel-listeners are exempt because they bypass DB registration entirely. Framework services that already provide names: ServiceWatcher (5), AppHandler (1), SessionManager (1). Need names added: StateProxy (1), RuntimeQueryService (~6). `topic` stays in the key because listeners routinely fan across multiple entities with the same logical name (e.g., `name="motion"` on both `light.kitchen` and `light.office`). Dropping `topic` would force globally-unique names within an app instance — stricter than any cited prior art. `handler_method` exits the key since `name` replaces its deduplication role — it stays as a display-only metadata column (used in 20+ query SELECTs and the frontend UI). `predicate_description` and `human_description` exit the identity and stay as metadata columns on the `listeners` table — both are still queried and displayed in the frontend (`telemetry_helpers.py:125`). This is a breaking API change. See `design/research/2026-05-28-handler-listener-identity/research.md` for the full survey.

- **Synchronous DB registration, single ID.** Eliminate the dual-ID architecture (`itertools.count` in-memory ID + async `db_id`). Registration becomes synchronous: the DB INSERT is awaited via `database_service.submit()` (not a blocking `sqlite3` call) during `on_initialize`, before the listener is routable. The database ID is the only ID. `BusService` gains `depends_on: [DatabaseService]` to guarantee DB readiness before any app's `on_initialize`. Each registration is a sequential `execute() + RETURNING` through the write queue (~1ms each) — `executemany` doesn't support per-row `RETURNING`, and the db_id must be known before the listener is routable. This removes: orphan telemetry records (executions with no FK), sentinel=0 filtering, `mark_registered()` ceremony, `registration_task` completion signals, `db_id` field, and counter-reset-on-restart confusion. Aligns with spec 060's direction of synchronous routing.

## Open Questions

- **What's the target file structure for the decomposed query service and repository?** #811 and #812 identified the current files as oversized. The rewrite is an opportunity to split them, but the target modules need to be decided during design.

- ~~**WebSocket message unification.**~~ **Decided:** Unify into a single `execution_completed` message with a discriminated union payload (`kind: "handler" | "job"`, `registration_id: int`, preserving `listener_id`/`job_id` as kind-specific fields). Matches the REST unification pattern. Frontend impacts: two signals (`invocationCompleted`, `executionCompleted`) merge into one, two WS handler `case` branches merge, and the per-listener/per-job cache invalidation predicates in `listener-detail.tsx:80` and `job-detail.tsx:66` must switch to the discriminated payload. `ws-types.ts` regeneration catches field-type mismatches but not behavioral logic in the predicate closures.

- **How should the seeding script (#854) relate to the new schema?** It should be built after schema stabilization, but should it be part of this round or explicitly deferred?

- ~~**Session drop counters.**~~ **Decided:** `dropped_no_session` becomes dead code with synchronous registration — the startup ordering guarantees `session_id` is always available before any listener is routable. Remove from `CommandExecutor`, `TelemetryStatusResponse`, and frontend status bar. Other drop counters (`dropped_overflow`, `dropped_exhausted`, `dropped_shutdown`) remain — they guard against write queue congestion, not session ordering.

- **Listener `name=` required: error UX.** When a user registers two handlers on the same entity without providing names, the collision error needs to be clear and actionable. What should the error message look like? Should the framework suggest a name based on context?

- **Migration runner design.** The `PRAGMA user_version` runner is ~30 lines, but decisions remain: plain `.sql` files or Python functions (for data migrations)? Where do migration files live? **Runner constraints (non-negotiable):** (1) Each migration runs inside `BEGIN IMMEDIATE` / `COMMIT`, with `PRAGMA user_version = N` as the final statement inside the transaction — crash between DDL and version update must not leave the DB at the wrong version. (2) Before running any migration on a fresh database, a raw `sqlite3.Connection` must check `PRAGMA auto_vacuum` and set `INCREMENTAL` if not already set — this runs outside any transaction, before the first DDL, because SQLite cannot change `auto_vacuum` on a database with existing pages. Both constraints are inherited from the current code (`database_service.py:504-517`).

## Scope Boundaries

**In scope (this round):**
- Unified `executions` table (replaces `handler_invocations` + `job_executions`)
- Sessions demoted to internal-only
- `app_key` → `owner_key` rename (#739)
- New columns: `trigger_mode` (#648), `retry_count`/`attempt_number` (#649), `args_json` (#650)
- Listener identity redesign: `name=` required, predicate exits identity
- Synchronous DB registration, single ID (eliminate dual-ID architecture)
- Replace Alembic with `PRAGMA user_version` + hand-rolled runner
- Migration chain reset (squash to 001)
- Migration-friendly schema design (no inline CHECK constraints)
- Unified REST API with discriminated union response types
- Unified WebSocket messages (`execution_completed` with discriminated union payload)
- Code decomposition of query service (#811) and repository (#812) as natural byproduct of rewrite
- Frontend type regeneration and component updates

**Explicitly deferred:**
- Statistics aggregation table (#672) — lands as an additive migration on the new foundation
- Per-app retention and pin mechanism (#651) — additive
- Configurable database intervals (#564) — config-only, no schema impact
- DB seeding script (#854) — build after schema stabilizes
- Execution registry (#834) — dropped, 404 after retention is acceptable

## Risks and Concerns

- **Battle-tested code gets rewritten.** The current write queue, retention cleanup, and size failsafe logic in `database_service.py` is stable. Rewriting the query/repository layer risks introducing bugs in the telemetry pipeline. Mitigation: keep `database_service.py` internals (queue, worker, pragmas, retention, failsafe) as unchanged as possible — the rewrite targets the schema, repository, query service, and API layer, not the write infrastructure. **Exception:** `_RETENTION_TABLES` and the parent-guard DELETE queries in `database_service.py` hard-code `handler_invocations` and `job_executions` table names — these are schema-coupled and must be updated to reference the unified `executions` table with `kind` discriminator filters. Without this, retention cleanup silently stops after the table rename.

- **Frontend breakage surface.** Changing from separate handler/job endpoints to a unified execution endpoint requires updating every frontend component that consumes telemetry data. The type regeneration pipeline (openapi-typescript) will catch type mismatches, but behavioral regressions (wrong data displayed, missing fields) need manual verification.

- **Migration-friendly schema is weaker at the DB level.** Moving CHECK constraints to application code means raw SQL (debugging, one-off queries, future tooling) won't have schema-level guardrails. Acceptable tradeoff for migration flexibility, but worth documenting.

- **Breaking API change (listener `name=` required).** Existing apps and examples that register listeners without `name=` will break. This is intentional — the prior art research confirms user-provided identity is the correct pattern — but requires migration guidance, clear error messages, and docs updates.

- **Breaking API change (`registration_task`, `db_id`, `mark_registered()` removed).** These are documented public API (handlers.md reference table, snippet examples, system tests use `sub.listener.db_id is not None` as a gate). Synchronous registration makes them unnecessary — registration is complete when `on_state_change()` returns. Migration guidance: remove `await sub.registration_task` calls and `db_id` checks; registration is guaranteed on return. Docs pages, snippets, and the Subscription reference table need updating.

- **Alembic removal ripple effects.** SQLAlchemy is currently imported only by Alembic. Removing Alembic drops SQLAlchemy as a dependency, which may affect type stubs, test fixtures, or any code that indirectly relied on SQLAlchemy being importable.

- **Scope creep from "while we're in here."** The temptation to fix adjacent issues (retention improvements, new aggregation, CLI changes) while rewriting the data layer. The scope boundary above is the firewall.

## Implementation Impact

### Synchronous Registration

The current registration flow already uses `await database_service.submit()` internally — it's the *spawning* that's async. The change eliminates the background task spawn and awaits inline.

**Files that change:**
- `core/bus_service.py` — `add_listener()` awaits `_register_in_db()` inline. Return type changes from `Task[None]` to `int`. `_reg_tracker` calls removed. `drain_framework_registrations()` deleted.
- `core/scheduler_service.py` — `_enqueue_then_register()` collapses. Job registration awaited before enqueuing to heap (eliminates `db_id=None` fire window).
- `bus/listeners.py` — `Subscription.registration_task` field removed.
- `bus/bus.py` — `_on_internal()` no longer captures a task into Subscription.
- `core/registration_tracker.py` — **entire class becomes dead code**. Both `BusService._reg_tracker` and `SchedulerService._reg_tracker` deleted.
- `core/app_lifecycle_service.py` — two `await_registrations_complete()` barrier calls removed.
- `core/core.py` — `await bus_service.drain_framework_registrations()` block removed.
- `bus/duration_hold.py` — pre-resolved Future for cancel-listener simplified.
- `bus/invocation.py` — lazy `listener.db_id` read becomes eager (guaranteed set before routable).

**Unchanged:** `CommandExecutor.register_listener/job()` (already uses `await submit()`), Router, `_dispatch_pending` tracking, execution record batching.

### Unified Executions Table

~215–260 lines net reduction across 7 files. Not purely mechanical due to handler-only columns (`trigger_context_id`, `trigger_origin` — NULL for jobs).

| File | Current | Reduction | Key changes |
|---|---|---|---|
| `telemetry_repository.py` | 687 | −55 to −65 | Two INSERT param builders → one. Dual `executemany` → one. Reconciliation queries filter by `kind`. |
| `telemetry_query_service.py` | 1187 | −65 to −85 | Mirrored pairs collapse. UNION ALL methods (`activity`, `errors`, `health`) need minimal change. `check_execution_predates_retention_cutoff` drops from 2 queries to 1. |
| `telemetry_models.py` | 338 | −25 to −30 | `HandlerInvocation` + `JobExecution` → unified `Execution` with `kind`. |
| `command_executor.py` | 956 | −55 to −60 | `_build_record` dual branches merge. `_persist_batch` dual-list logic halves. `RetryableBatch` simplifies. |
| `web/routes/telemetry.py` | 376 | −15 to −20 | Route pair shares a helper. |
| `web/models.py` | 483 | −20 | WS message types merge. |
| `database_service.py` | — | −15 | `_RETENTION_TABLES` and parent-guard queries update. |

**Models that stay split:** `ListenerSummary` and `JobSummary` are structurally too different (handler has topic/debounce/throttle; job has trigger_type/group/next_run). Their query methods remain separate.

### Alembic Removal

All Alembic/SQLAlchemy references live in one file plus the migrations directory. Surprisingly contained.

- `core/database_service.py` — 5 imports deleted. 3 methods rewritten: `_get_expected_head_revision()`, `_get_current_db_revision()`, `_run_migrations()`. The mismatch logic in `_handle_schema_version()` survives with integer comparison instead of string.
- `src/hassette/migrations/` — 14 files deleted (env.py, script.py.mako, 10 version files, 2 __init__.py).
- `alembic.ini` — deleted.
- `pyproject.toml` — remove `alembic>=1.13`. SQLAlchemy and Mako disappear as transitive deps.
- **New code:** ~35 lines (migration runner function + `PRAGMA user_version` read/write) + plain `.sql` files extracted from existing version files.

No other Python file imports alembic or sqlalchemy.

### Frontend

| Area | Files | Change type |
|---|---|---|
| Type regen | `generated-types.ts`, `ws-types.ts` | Mechanical — run `export_schemas.py --types` |
| WS handler | `use-websocket.ts`, `create-app-state.ts` | Two signals merge to one. Two `case` branches merge. |
| Detail pages | `listener-detail.tsx`, `job-detail.tsx` | API call updates (new endpoint paths). |
| Cache invalidation | Both detail pages + `recent-activity-section.tsx` | Predicate closures change to discriminated union matching. |
| Combined views | `handlers.tsx`, `handler-rows.ts` | Type updates for new models. |
| Status bar | `use-telemetry-health.ts`, `alert-banner.tsx`, `status-bar.tsx`, `diagnostics.tsx` | Remove `droppedNoSession` signal and badge. |
| Routing | `handlers-tab.tsx`, `palette-items.ts` | Delete `handler-ids.ts`. Switch to `/listener/:id` and `/job/:id`. |
| Query keys | `query-keys.ts` | `handlerInvocations`/`jobExecutions` merge or rename. |
| Endpoints | `endpoints.ts` | URL paths update to unified endpoint. |

## Codebase Context

- **Current schema:** 6 tables, 10 migrations, ~20 indexes. `handler_invocations` (16 columns) and `job_executions` (14 columns) share ~90% of their structure.
- **Query service:** `telemetry_query_service.py` at 1188 lines with mirrored query pairs for handlers vs jobs. `get_listener_summary()` and `get_job_summary()` are ~100 LOC each, nearly line-for-line identical.
- **Repository:** `telemetry_repository.py` at 688 lines with duplicated insert builders, batch persist logic, and reconciliation.
- **Web models:** `telemetry_models.py` (339 lines) has parallel model pairs: `ListenerSummary`/`JobSummary`, `HandlerInvocation`/`JobExecution`, `HandlerErrorRecord`/`JobErrorRecord`.
- **Frontend:** Consumes data via REST + WebSocket. Separate endpoints for handler invocations and job executions. `ActivityFeedEntry` already has a `kind: "handler" | "job"` discriminator — the unified pattern exists in embryonic form.
- **Existing discriminated union pattern:** `WsServerMessage` in `models.py` uses `Annotated[... | ..., Field(discriminator="type")]` — the exact pattern the unified API should follow.
- **Delete-recreate trigger:** `_handle_schema_version()` in `database_service.py` compares Alembic head revision with DB revision. Mismatch → delete DB files (including WAL/SHM) → recreate on fresh migrations.
- **Typical DB size:** <50 MB for home automation workloads. 7-day default retention. Hourly cleanup. Size failsafe at 500 MB.
- **Prior art research:** `design/research/2026-05-02-db-table-design-telemetry/research.md` analyzed 7 comparable frameworks (Temporal, Airflow, Prefect, Celery, n8n). Hassette's single-writer queue pattern matches HA's recorder.
