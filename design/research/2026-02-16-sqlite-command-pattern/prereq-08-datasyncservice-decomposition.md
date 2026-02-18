# Prereq 8: DataSyncService Decomposition

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 4: Frontend query requirements](./prereq-04-frontend-query-requirements.md) — defines the query patterns the new layer(s) must serve
- [Prereq 5: Schema design](./prereq-05-schema-design.md) — DB structure for telemetry queries

## Dependents

- None (implementation-time concern, but shapes the web layer migration)

## Problem

`DataSyncService` (`core/data_sync_service.py`) is a monolithic facade that aggregates data from multiple in-memory sources (BusService, SchedulerService, AppHandler, StateProxy, LogCaptureHandler, event buffer) and presents it to the web layer. It was a proof of concept — every web route depends on `DataSyncDep`.

With the DB migration:
- Telemetry reads (listener metrics, job execution history, session data) move from in-memory structures to DB queries
- Runtime state reads (app status, entity states, scheduled job `next_run`, logs, events) stay in-memory
- The "sync" in the name was never accurate — it's a read-only query layer, not a synchronization mechanism

The facade mixes two fundamentally different data sources with different characteristics (DB queries with latency vs in-memory lookups that are instant). Keeping them in one class obscures this and makes it harder to reason about performance.

## Questions to answer

1. **Decompose or rename?** Split into separate services for telemetry (DB) and runtime state (in-memory), or keep a single facade with a better name?
2. **If decomposed, what are the boundaries?** Which methods go where? Do web routes call multiple services directly, or is there still a thin coordination layer?
3. **What happens to `DataSyncDep`?** Every web route and partial currently depends on it. If decomposed, routes need new dependency injection.
4. **Where do the owner-mapping methods go?** `get_user_app_owner_map()` and `get_instance_owner_map()` translate between `app_key` and `owner_id`. With structured identity fields (`app_key` + `instance_index`) in the DB, these may become unnecessary.

## Scope

- Audit all `DataSyncService` public methods and classify as telemetry vs runtime
- Decide on decomposition strategy
- Define new service boundaries and naming
- Plan the migration path for web routes

This is an architectural decision that should be made before implementation begins, but doesn't block any of the other prereqs.
