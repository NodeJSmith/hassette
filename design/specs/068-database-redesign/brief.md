# Brief: Database Schema Redesign

**Date:** 2026-05-28
**Status:** explored

## Idea

Rewrite hassette's telemetry database schema to unify the duplicated execution tables, demote sessions to internal-only, fold in pending schema enhancements, replace Alembic with `PRAGMA user_version` for migrations, and redesign listener identity around user-provided names. The migration chain resets to a single 001 (one final delete-recreate), after which all future schema changes use proper forward migrations instead of delete-recreate.

**Forcing function:** Implementing `if_exists` for listener registration (#779) is blocked by friction in the database registration and deduplication logic. The current schema shape contributes to that friction.

## Key Decisions Made

- **Unified executions table.** `handler_invocations` and `job_executions` merge into a single `executions` table with a `kind` discriminator. Registration tables (`listeners`, `scheduled_jobs`) stay separate — their schemas are genuinely different.

- **Sessions become internal-only.** The `sessions` table stays for crash recording, heartbeat, and drop counters, but `session_id` is not exposed in the API or frontend. No sessions endpoint, no session-based filtering. Time-based filtering is the only user-facing grain.

- **Integer PK + UUID column.** Auto-increment `id` as primary key, `execution_id` as a unique indexed UUID column. Matches the current pattern, best SQLite write locality.

- **Discriminated union API.** The unified API returns `kind: Literal["handler"]` or `kind: Literal["job"]` on execution records, using the same Pydantic discriminated union pattern already used for WebSocket messages. openapi-typescript generates clean TypeScript unions from this.

- **#834 (execution registry) dropped.** 404 after retention purge is acceptable — matches HA's behavior for traces and history. No tombstone table needed.

- **Validation moves to application layer.** No inline CHECK constraints in the schema (they prevent ALTER TABLE in SQLite). All validation in Pydantic models and repository code. Schema contains columns, indexes, and foreign keys only.

- **Migration chain resets to 001.** The new schema is migration 001. Old databases get one final delete-recreate. After this, real forward migrations for all future changes.

- **Replace Alembic with `PRAGMA user_version`.** Alembic's value-adds (auto-generation, ORM diffing, branching, downgrades) are unused — all migrations are hand-written SQL. SQLite's built-in `user_version` pragma + a ~30-line runner replaces the entire Alembic + SQLAlchemy + Mako dependency chain. This is the standard pattern for embedded SQLite (Android, Firefox, Chromium). See research notes below.

- **`app_key` renames to `owner_key`.** Across all tables (#739).

- **New columns baked into the initial schema.** `trigger_mode` (#648), `retry_count`/`attempt_number` (#649), `args_json`/`kwargs_json` (#650) land in the unified executions table from day one, avoiding future ALTER TABLE for known requirements.

- **Listener identity redesign: `name` becomes required.** Prior art research (Django dispatch_uid, Temporal Workflow ID, Celery task names, AppDaemon) confirms that user-provided stable keys are the industry standard for idempotent registration. The current computed identity (predicate summary in the natural key) is fragile and not used by any comparable framework. `name=` becomes required on listener registration, making the natural key `(owner_key, instance_index, name)` — symmetric with scheduled jobs. Predicate description exits the identity and stays as metadata. This is a breaking API change. See `design/research/2026-05-28-handler-listener-identity/research.md` for the full survey.

- **Synchronous DB registration, single ID.** Eliminate the dual-ID architecture (`itertools.count` in-memory ID + async `db_id`). Registration becomes synchronous: the DB INSERT happens inline during `on_initialize`, before the listener is routable. The database ID is the only ID. This removes: orphan telemetry records (executions with no FK), sentinel=0 filtering, `mark_registered()` ceremony, `registration_task` completion signals, `db_id` field, and counter-reset-on-restart confusion. Cost is ~1ms per listener at startup (negligible). Aligns with spec 060's direction of synchronous routing.

## Open Questions

- **What's the target file structure for the decomposed query service and repository?** #811 and #812 identified the current files as oversized. The rewrite is an opportunity to split them, but the target modules need to be decided during design.

- **WebSocket message unification.** Currently separate `invocation_completed` and `execution_completed` message types. Should these merge into a single `execution_completed` with a `kind` field, or stay separate? (Probably merge to match the API pattern.)

- **How should the seeding script (#854) relate to the new schema?** It should be built after schema stabilization, but should it be part of this round or explicitly deferred?

- **Session drop counters.** Currently tracked per-session (`dropped_overflow`, `dropped_exhausted`, etc.). If sessions are internal-only, are these still useful? Do they need to be surfaced elsewhere (e.g., health endpoint)?

- **Listener `name=` required: error UX.** When a user registers two handlers on the same entity without providing names, the collision error needs to be clear and actionable. What should the error message look like? Should the framework suggest a name based on context?

- **Migration runner design.** The `PRAGMA user_version` runner is ~30 lines, but decisions remain: plain `.sql` files or Python functions (for data migrations)? Where do migration files live? How does the runner handle failures mid-migration (partial application)?

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
- Unified WebSocket messages (TBD — see open questions)
- Code decomposition of query service (#811) and repository (#812) as natural byproduct of rewrite
- Frontend type regeneration and component updates

**Explicitly deferred:**
- Statistics aggregation table (#672) — lands as an additive migration on the new foundation
- Per-app retention and pin mechanism (#651) — additive
- Configurable database intervals (#564) — config-only, no schema impact
- DB seeding script (#854) — build after schema stabilizes
- Execution registry (#834) — dropped, 404 after retention is acceptable

## Risks and Concerns

- **Battle-tested code gets rewritten.** The current write queue, retention cleanup, and size failsafe logic in `database_service.py` is stable. Rewriting the query/repository layer risks introducing bugs in the telemetry pipeline. Mitigation: keep `database_service.py` internals (queue, worker, pragmas, retention, failsafe) as unchanged as possible — the rewrite targets the schema, repository, query service, and API layer, not the write infrastructure.

- **Frontend breakage surface.** Changing from separate handler/job endpoints to a unified execution endpoint requires updating every frontend component that consumes telemetry data. The type regeneration pipeline (openapi-typescript) will catch type mismatches, but behavioral regressions (wrong data displayed, missing fields) need manual verification.

- **Migration-friendly schema is weaker at the DB level.** Moving CHECK constraints to application code means raw SQL (debugging, one-off queries, future tooling) won't have schema-level guardrails. Acceptable tradeoff for migration flexibility, but worth documenting.

- **Breaking API change (listener `name=` required).** Existing apps and examples that register listeners without `name=` will break. This is intentional — the prior art research confirms user-provided identity is the correct pattern — but requires migration guidance, clear error messages, and docs updates.

- **Alembic removal ripple effects.** SQLAlchemy is currently imported only by Alembic. Removing Alembic drops SQLAlchemy as a dependency, which may affect type stubs, test fixtures, or any code that indirectly relied on SQLAlchemy being importable.

- **Scope creep from "while we're in here."** The temptation to fix adjacent issues (retention improvements, new aggregation, CLI changes) while rewriting the data layer. The scope boundary above is the firewall.

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
